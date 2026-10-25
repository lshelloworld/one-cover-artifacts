"""Repository-wide settings. Every script imports this module (through its header),
which also makes the repository root the working directory, so all paths in the
scripts are relative to the root. The database login comes from the environment."""
import os
ROOT = os.path.dirname(os.path.abspath(__file__))
DSN = dict(host=os.environ.get('ONECOVER_DB_HOST', 'localhost'),
           port=int(os.environ.get('ONECOVER_DB_PORT', '5432')),
           user=os.environ.get('ONECOVER_DB_USER', 'postgres'),
           password=os.environ.get('ONECOVER_DB_PASSWORD', ''),
           dbname=os.environ.get('ONECOVER_DB_NAME', 'onecover'))
