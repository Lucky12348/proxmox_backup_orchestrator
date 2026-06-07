import assert from "node:assert/strict";
import test from "node:test";

import { coerceAutoEjectAfterSuccess, getDiskDisplayCapacityGb } from "../src/diskPlanning.ts";

test("getDiskDisplayCapacityGb falls back to total capacity when usable capacity is missing", () => {
  assert.equal(getDiskDisplayCapacityGb({ usable_capacity_gb: null, capacity_gb: 4000 }), 4000);
  assert.equal(getDiskDisplayCapacityGb({ usable_capacity_gb: 1250, capacity_gb: 4000 }), 1250);
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
