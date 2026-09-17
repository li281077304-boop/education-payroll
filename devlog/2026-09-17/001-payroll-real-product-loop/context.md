# Context

## USER OBSERVATION

The user performed a real manual Payroll UAT on 2026-09-17 and supplied two durable source documents. The observed issues include teacher-filter focus loss, unclear issue expansion, missing two-way special-case entry, a failed 30-hour confirmation, an incomplete base-salary path, dense preview presentation, suspected default-two-star behavior, and a non-company-template export.

## CONFIRMED FACT

The two source documents were read from the user's Downloads directory and copied into the Payroll repository's durable UAT area with verified SHA-256 fingerprints. The canonical checkout is `/private/tmp/education-payroll-host-chief.h2CabN`, starting at `ec1fe201077aa6f41e2aa2a3dd62f63ef875ec49`. Existing runtime artifacts were preserved.

## TECHNICAL ASSESSMENT

The task is a real product loop: fix root causes in the local Payroll UI/core, protect July/August isolation, and verify through focused tests, full tests, and a manual UAT replay. Business rules must come from existing evidence; unknown rules remain unresolved rather than guessed.

## REJECTED ASSUMPTIONS

- The UAT text is not itself a new business rule.
- A UI green state is not sufficient without durable persistence and reload verification.
- A custom generated workbook is not an acceptable substitute for the company's existing payroll template.

## DECISION

Use `payroll-uat-20260917-r1` on branch `feature/payroll-uat-20260917-loop`, with Host Sol High as primary Chief, Luna Worker turns, fail-closed Machine Gate, and durable evidence for every phase.

## UNKNOWN / OPEN RISKS

- The source traceback for error `4ac7c59609da3256` must be located before changing the 30-hour path.
- The real company template must be identified before export can pass.
