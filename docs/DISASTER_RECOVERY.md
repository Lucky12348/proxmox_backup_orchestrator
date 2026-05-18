# Disaster Recovery

Scenario: the original Proxmox server is lost. The external USB disk contains a dedicated PBS datastore created by Proxmox Backup Orchestrator.

Goal: rebuild enough infrastructure to mount/import that datastore and restore VMs or containers.

## 1. Reinstall Proxmox

Install Proxmox VE on replacement hardware.

After installation:

- configure management networking
- install updates
- restore or recreate storage/network names as needed
- do not format the external USB backup disk

## 2. Create or Import a PBS VM

If you have a PBS VM backup outside the lost host, restore it first.

If not, create a new PBS VM:

1. Install Proxmox Backup Server.
2. Configure networking.
3. Update packages.
4. Confirm the PBS web UI and API are reachable on port `8007`.

The new PBS VM does not need the old app database to read the external datastore.

## 3. Attach the External USB Disk

Plug the external disk into the Proxmox host.

Identify it carefully:

```bash
lsblk -o NAME,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINTS
```

Attach it to the PBS VM through the Proxmox UI or CLI. Example:

```bash
qm set <pbs-vm-id> -usb0 host=<vendor-id>:<product-id>,usb3=1
```

Prefer a stable device identity from the Proxmox UI when possible. Do not initialize or wipe the disk.

## 4. Mount the Datastore in PBS

Inside the PBS VM, inspect the disk:

```bash
lsblk -f
blkid
```

Create a mount point:

```bash
mkdir -p /mnt/pbo-recovery/external-datastore
```

Mount the partition that contains the PBS datastore:

```bash
mount /dev/disk/by-uuid/<uuid> /mnt/pbo-recovery/external-datastore
```

Find the datastore directory. Dedicated disks normally contain a PBS datastore prepared by the PBS agent. If you do not know the exact path, inspect:

```bash
find /mnt/pbo-recovery/external-datastore -maxdepth 3 -type d -name ".chunks" -print
```

The datastore path is the parent directory that contains `.chunks`.

## 5. Import or Add the PBS Datastore

In the PBS web UI:

1. Go to Datastore.
2. Add datastore.
3. Use a recovery name such as `external-recovery`.
4. Set the backing path to the directory that contains `.chunks`.

Or use CLI:

```bash
proxmox-backup-manager datastore create external-recovery /mnt/pbo-recovery/external-datastore/<datastore-path>
```

Then verify:

```bash
proxmox-backup-manager datastore list
proxmox-backup-client snapshots --repository <user>@pam@localhost:external-recovery
```

## 6. Add PBS Storage in Proxmox

In Proxmox VE:

1. Datacenter -> Storage -> Add -> Proxmox Backup Server.
2. Enter the PBS server address.
3. Choose datastore `external-recovery`.
4. Configure credentials or API token.
5. Enable the storage for the required nodes.

Verify that backup groups and snapshots appear in the Proxmox restore UI.

## 7. Restore VM or CT

From the Proxmox UI:

1. Select the PBS storage.
2. Select the VM or CT backup snapshot.
3. Click Restore.
4. Choose a new VMID if the original ID conflicts.
5. Choose target storage.
6. Restore.

CLI examples:

```bash
qmrestore <pbs-storage>:backup/vm/<vmid>/<snapshot> <new-vmid> --storage <target-storage>
pct restore <new-ctid> <pbs-storage>:backup/ct/<ctid>/<snapshot> --storage <target-storage>
```

Use the exact volume names shown by Proxmox or `pvesm list <pbs-storage>`.

## Validation Checklist

- Proxmox host is reachable and updated.
- PBS VM is reachable on port `8007`.
- External USB disk was attached without formatting.
- Disk partition is mounted read/write or read-only as intended.
- PBS datastore path contains `.chunks`.
- PBS datastore appears in `proxmox-backup-manager datastore list`.
- Proxmox storage points to the recovery datastore.
- Target VM/CT restores successfully.
- Restored guest boots.
- Critical application data is present.
- Network configuration is corrected for the replacement environment.
- A new backup run succeeds after recovery.

## After Recovery

Once workloads are restored, reinstall Proxmox Backup Orchestrator if desired:

1. Install the app VM.
2. Install the Proxmox host agent.
3. Install the PBS agent.
4. Reuse the same external disk only after verifying the restored PBS datastore setup.

Keep the old external disk offline until you have at least one new successful backup on replacement infrastructure.
