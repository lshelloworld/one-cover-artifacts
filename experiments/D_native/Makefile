MODULE_big = nbtnull
OBJS = nbtnull.o
PG_CONFIG ?= /Library/PostgreSQL/18/bin/pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)
# the EDB build of PostgreSQL records an SDK this machine does not have; use the installed one, native arch only
PG_SYSROOT := $(shell xcrun --show-sdk-path)
override CFLAGS := $(subst -arch x86_64,,$(CFLAGS))
override LDFLAGS := $(subst -arch x86_64,,$(LDFLAGS))
