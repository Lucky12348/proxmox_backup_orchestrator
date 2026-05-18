# Disaster Recovery Restore

## Goal

Recover backups from a dedicated external Proxmox Backup Server datastore disk.

This guide assumes the external disk was prepared by Proxmox Backup Orchestrator as a dedicated PBS datastore disk.

## Scenario

Proxmox and/or PBS has been reinstalled from scratch, but the external USB backup disk is still available.

Important: do not format the disk during restore. The goal is to mount the existing PBS datastore and register it again.

## Example

- datastore: `pbo-wd-wxd2da1l1e7c`
- path: `/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore`

## Restore Steps

1. Attach the USB disk to the PBS VM.

2. Identify the disk and partition:

   ```bash
   lsblk -f
   ```

   Look for the external disk and its ext4 partition, for example `/dev/sdc1`.

3. Create the expected mount path:

   ```bash
   mkdir -p /mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore
   ```

4. Mount the existing partition:

   ```bash
   mount /dev/sdc1 /mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore
   ```

5. Ensure PBS can read and write the datastore:

   ```bash
   chown backup:backup /mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore
   chmod 750 /mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore
   ```

6. Recreate the PBS datastore entry using the existing datastore data:

   ```bash
   proxmox-backup-manager datastore create pbo-wd-wxd2da1l1e7c /mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore --reuse-datastore true
   ```

7. Verify snapshots are visible.

   In the PBS UI, open the datastore and check that snapshots appear.

   Or use:

   ```bash
   proxmox-backup-manager datastore list
   proxmox-backup-client snapshot list --repository localhost:pbo-wd-wxd2da1l1e7c
   ```

## Checklist

- USB disk attached to the PBS VM.
- Correct partition identified with `lsblk -f`.
- Existing partition mounted, not formatted.
- Mount path ownership is `backup:backup`.
- Mount path mode is `750`.
- Datastore recreated with `--reuse-datastore true`.
- Snapshots visible in PBS UI or CLI.
