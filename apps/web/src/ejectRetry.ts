import type { ExternalBackupRun } from "./types";

// Step the API records when the agent's write-cache flush timed out: nothing
// was unmounted or detached, so the disk must stay plugged in.
export const EJECT_NOT_FINISHED_STEP = "eject_not_finished";

// An eject can be retried only from the latest run of its disk: a later run
// (retry, new backup) supersedes the warning.
type EjectRunFields = Pick<ExternalBackupRun, "id" | "disk_id" | "status" | "current_step">;

export function retryableEjectRunIds(runs: EjectRunFields[]): Set<number> {
  const latestByDisk = new Map<number, EjectRunFields>();
  for (const run of runs) {
    const current = latestByDisk.get(run.disk_id);
    if (!current || run.id > current.id) {
      latestByDisk.set(run.disk_id, run);
    }
  }
  return new Set(
    [...latestByDisk.values()]
      .filter((run) => run.status === "failed" && run.current_step === EJECT_NOT_FINISHED_STEP)
      .map((run) => run.id),
  );
}
