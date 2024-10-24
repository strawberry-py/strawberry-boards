"""This is an example on how to handle DB updates from version to version

The name of the file must be update_{version}_to_{version+1}.py
For example: `update_1_to_2.py`
The file must be placed into folder `updates` located in the same directory
as database.py file for the module
For example:
    `./pie/acl/updates/update_1_to_2.py`
    `./modules/base/errors/updates/update_1_to_2.py`

The update can be done only from version to version + 1 (can't skip versions).

The inspector should be used to figure out if the update is needed.
It might happen that the module with newer schema is freshly installed
before the core is updated to the version that supports DB updates
"""

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import BigInteger, inspect

from pie.database import database


def run():
    inspector = inspect(database.db)
    with database.db.connect() as conn:
        mc = MigrationContext.configure(conn)
        with mc.begin_transaction():
            ops = Operations(mc)

            karma_columns = [
                column["name"]
                for column in inspector.get_columns("boards_karma_members")
            ]

            if "guild_id" in karma_columns:
                ops.alter_column(
                    "boards_karma_members", column_name="guild_id", type_=BigInteger
                )
