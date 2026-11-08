import assert from "node:assert/strict";
import test from "node:test";

import { EJECT_NOT_FINISHED_STEP, retryableEjectRunIds } from "../src/ejectRetry.ts";

function run(id: number, diskId: number, status: "success" | "failed" | "running", step: string | null) {
  return { id, disk_id: diskId, status, current_step: step } as const;
}

test("retryableEjectRunIds offers retry on the latest run when its eject did not finish", () => {
  const runs = [run(1, 10, "success", "success"), run(2, 10, "failed", EJECT_NOT_FINISHED_STEP)];
  assert.deepEqual([...retryableEjectRunIds(runs)], [2]);
});

test("retryableEjectRunIds ignores a not-finished eject superseded by a later run of the same disk", () => {
  const runs = [run(3, 10, "success", "ejected"), run(2, 10, "failed", EJECT_NOT_FINISHED_STEP)];
  assert.equal(retryableEjectRunIds(runs).size, 0);
});

test("retryableEjectRunIds ignores other failures and keeps disks independent", () => {
  const runs = [
    run(4, 10, "failed", "failure"),
    run(5, 11, "failed", EJECT_NOT_FINISHED_STEP),
    run(6, 12, "running", "eject_flush"),
  ];
  assert.deepEqual([...retryableEjectRunIds(runs)], [5]);
});
