export PG_TARGET_DIR=/workspaces/pg_dev/pg_lab/pg-build/pg-18
export PATH="$PG_TARGET_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$PG_TARGET_DIR/lib:$LD_LIBRARY_PATH"
export C_INCLUDE_PATH="$PG_TARGET_DIR/include/server:$C_INCLUDE_PATH"
export PGDATA="$PG_TARGET_DIR/data"
