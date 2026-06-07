import assert from "node:assert/strict";
import test from "node:test";

import { coerceAutoEjectAfterSuccess, getDiskDisplayCapacityGb, getDiskFilesystemUsage } from "../src/diskPlanning.ts";

test("getDiskDisplayCapacityGb falls back to total capacity when usable capacity is missing", () => {
  assert.equal(getDiskDisplayCapacityGb({ usable_capacity_gb: null, capacity_gb: 4000 }), 4000);
  assert.equal(getDiskDisplayCapacityGb({ usable_capacity_gb: 1250, capacity_gb: 4000 }), 1250);
});

test("getDiskFilesystemUsage returns null when real filesystem metrics are unavailable", () => {
  assert.equal(
    getDiskFilesystemUsage({
      filesystem_total_gb: null,
      filesystem_used_gb: null,
      filesystem_free_gb: null,
    }),
    null,
  );
  assert.deepEqual(
    getDiskFilesystemUsage({
      filesystem_total_gb: 3726,
      filesystem_used_gb: 1200,
      filesystem_free_gb: 2526,
    }),
    { total: 3726, used: 1200, free: 2526 },
  );
});

test("coerceAutoEjectAfterSuccess disables auto-eject for non dedicated disks", () => {
  assert.equal(
    coerceAutoEjectAfterSuccess(
      {
        dedicated_backup_disk: false,
        prepared_as_pbs_datastore: false,
      },
      true,
    ),
    false,
  );
  assert.equal(
    coerceAutoEjectAfterSuccess(
      {
        dedicated_backup_disk: true,
        prepared_as_pbs_datastore: false,
      },
      true,
    ),
    true,
  );
});
