#!/bin/bash
# Starts MySQL key set 2, |Σ|=40, both sides, once the machine is quiet: the 5-minute load below 4 for 10 minutes running.
cd "$(dirname "$0")/../.."
L=results/D_enforcement/mysql_repeat.log; echo "waiting since $(date) for the 5-minute load to stay below 4 for 10 minutes" >> $L
q=0; while [ $q -lt 10 ]; do l=$(sysctl -n vm.loadavg | awk '{print $3}'); if awk "BEGIN{exit !($l<4)}"; then q=$((q+1)); else q=0; fi; sleep 60; done
echo "quiet since $(date '+%H:%M'), load $(sysctl -n vm.loadavg)" >> $L
exec results/D_enforcement/run_mysql_repeat.sh 2 40
