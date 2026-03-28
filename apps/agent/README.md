# Agent

Python agent placeholder intended to run on a Proxmox host.

## Purpose

This component will later:

- detect attached USB disks
- report disk state back to the API
- help coordinate removable-media backup workflows

## Run locally

1. Create a virtual environment.
2. Install the package with `pip install -e .`
3. Run `python -m agent.main`
