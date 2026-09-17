# Decision

The supplied manual UAT remains the acceptance contract. The 30-hour failure is confirmed as SQLite lock contention, so it is handled as a technical defect rather than HUMAN_REQUIRED. WAL/busy-timeout and duplicate-submit protection are now part of the durable implementation contract.

Missing star authority/reference is not converted to a default two-star result. Company-template export is fail-closed. Base-salary values, template binding, and real policy exceptions remain explicit human boundary items; the system must not guess them.
