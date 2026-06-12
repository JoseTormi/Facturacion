from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from saef.models import FacturaExtraida, Proveedor


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def ensure_schema(self) -> None:
        with closing(self.connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS proveedores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL UNIQUE,
                    tipo TEXT NOT NULL,
                    activo INTEGER NOT NULL DEFAULT 1,
                    remitente TEXT,
                    asunto TEXT,
                    creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS periodos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mes TEXT NOT NULL UNIQUE,
                    estado TEXT NOT NULL DEFAULT 'pendiente',
                    creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS facturas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proveedor_id INTEGER,
                    proveedor TEXT NOT NULL,
                    numero TEXT,
                    fecha TEXT,
                    valor NUMERIC,
                    moneda TEXT,
                    estado TEXT NOT NULL,
                    ruta_pdf TEXT,
                    periodo TEXT NOT NULL,
                    creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(proveedor_id) REFERENCES proveedores(id)
                );
                """
            )
            self._ensure_invoice_indexes(connection)

    def upsert_provider(
        self,
        *,
        nombre: str,
        tipo: str,
        activo: bool,
        remitente: str | None = None,
        asunto: str | None = None,
    ) -> None:
        with closing(self.connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO proveedores (nombre, tipo, activo, remitente, asunto)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(nombre) DO UPDATE SET
                    tipo = excluded.tipo,
                    activo = excluded.activo,
                    remitente = excluded.remitente,
                    asunto = excluded.asunto,
                    actualizado_en = CURRENT_TIMESTAMP
                """,
                (nombre, tipo, int(activo), remitente or None, asunto or None),
            )

    def sync_gmail_provider_from_env(
        self,
        *,
        nombre: str,
        activo: bool,
        remitente: str,
        asunto: str,
    ) -> None:
        if not activo:
            return
        if not remitente and not asunto:
            return
        self.upsert_provider(
            nombre=nombre,
            tipo="gmail",
            activo=True,
            remitente=remitente or None,
            asunto=asunto or None,
        )

    def list_active_providers(self) -> list[Proveedor]:
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT id, nombre, tipo, activo, remitente, asunto
                FROM proveedores
                WHERE activo = 1
                ORDER BY nombre
                """
            ).fetchall()
        return [self._provider_from_row(row) for row in rows]

    def upsert_period(self, mes: str, estado: str) -> None:
        with closing(self.connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO periodos (mes, estado)
                VALUES (?, ?)
                ON CONFLICT(mes) DO UPDATE SET
                    estado = excluded.estado,
                    actualizado_en = CURRENT_TIMESTAMP
                """,
                (mes, estado),
            )

    def save_invoices(self, invoices: Iterable[FacturaExtraida]) -> None:
        with closing(self.connect()) as connection, connection:
            for invoice in invoices:
                provider_id = self._provider_id(connection, invoice.proveedor)
                connection.execute(
                    """
                    INSERT INTO facturas (
                        proveedor_id, proveedor, numero, fecha, valor, moneda,
                        estado, ruta_pdf, periodo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(periodo, ruta_pdf) DO UPDATE SET
                        proveedor_id = excluded.proveedor_id,
                        proveedor = excluded.proveedor,
                        numero = excluded.numero,
                        fecha = excluded.fecha,
                        valor = excluded.valor,
                        moneda = excluded.moneda,
                        estado = excluded.estado,
                        actualizado_en = CURRENT_TIMESTAMP
                    """,
                    (
                        provider_id,
                        invoice.proveedor,
                        invoice.numero,
                        invoice.fecha.isoformat() if invoice.fecha else None,
                        str(invoice.valor) if invoice.valor is not None else None,
                        invoice.moneda,
                        invoice.estado,
                        str(invoice.ruta_pdf) if invoice.ruta_pdf else None,
                        invoice.periodo,
                    ),
                )

    def delete_invoices(self, periodo: str) -> None:
        with closing(self.connect()) as connection, connection:
            connection.execute(
                """
                DELETE FROM facturas
                WHERE periodo = ?
                """,
                (periodo,),
            )

    def list_invoices(self, mes: str) -> list[FacturaExtraida]:
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT id, proveedor, numero, fecha, valor, moneda, estado, ruta_pdf, periodo
                FROM facturas
                WHERE periodo = ?
                ORDER BY proveedor, fecha, numero, ruta_pdf
                """,
                (mes,),
            ).fetchall()
        return [self._invoice_from_row(row) for row in rows]

    def get_invoice(self, invoice_id: int) -> FacturaExtraida | None:
        with closing(self.connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT id, proveedor, numero, fecha, valor, moneda, estado, ruta_pdf, periodo
                FROM facturas
                WHERE id = ?
                """,
                (invoice_id,),
            ).fetchone()
        return self._invoice_from_row(row) if row else None

    def _ensure_invoice_indexes(self, connection: sqlite3.Connection) -> None:
        table_row = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'facturas'
            """
        ).fetchone()
        table_sql = table_row["sql"] if table_row else ""

        if "UNIQUE(proveedor, numero, periodo)" in table_sql:
            connection.executescript(
                """
                ALTER TABLE facturas RENAME TO facturas_old;

                CREATE TABLE facturas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proveedor_id INTEGER,
                    proveedor TEXT NOT NULL,
                    numero TEXT,
                    fecha TEXT,
                    valor NUMERIC,
                    moneda TEXT,
                    estado TEXT NOT NULL,
                    ruta_pdf TEXT,
                    periodo TEXT NOT NULL,
                    creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(proveedor_id) REFERENCES proveedores(id)
                );

                INSERT INTO facturas (
                    id, proveedor_id, proveedor, numero, fecha, valor, moneda,
                    estado, ruta_pdf, periodo, creado_en, actualizado_en
                )
                SELECT
                    id, proveedor_id, proveedor, numero, fecha, valor, moneda,
                    estado, ruta_pdf, periodo, creado_en, actualizado_en
                FROM facturas_old;

                DROP TABLE facturas_old;
                """
            )

        connection.execute(
            """
            DELETE FROM facturas
            WHERE ruta_pdf IS NOT NULL
              AND id NOT IN (
                  SELECT MAX(id)
                  FROM facturas
                  WHERE ruta_pdf IS NOT NULL
                  GROUP BY periodo, ruta_pdf
              )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_facturas_periodo_ruta_pdf
            ON facturas(periodo, ruta_pdf)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_facturas_periodo
            ON facturas(periodo)
            """
        )

    def _provider_id(self, connection: sqlite3.Connection, nombre: str) -> int | None:
        row = connection.execute(
            "SELECT id FROM proveedores WHERE nombre = ?",
            (nombre,),
        ).fetchone()
        return int(row["id"]) if row else None

    def _provider_from_row(self, row: sqlite3.Row) -> Proveedor:
        return Proveedor(
            id=row["id"],
            nombre=row["nombre"],
            tipo=row["tipo"],
            activo=bool(row["activo"]),
            remitente=row["remitente"],
            asunto=row["asunto"],
        )

    def _invoice_from_row(self, row: sqlite3.Row) -> FacturaExtraida:
        return FacturaExtraida(
            id=row["id"] if "id" in row.keys() else None,
            proveedor=row["proveedor"],
            numero=row["numero"],
            fecha=date.fromisoformat(row["fecha"]) if row["fecha"] else None,
            valor=Decimal(str(row["valor"])) if row["valor"] is not None else None,
            moneda=row["moneda"],
            estado=row["estado"],
            ruta_pdf=Path(row["ruta_pdf"]) if row["ruta_pdf"] else None,
            periodo=row["periodo"],
        )
