# FJSP data

## Source and local migration

The 60 fixed split instances were copied byte-for-byte from:

```text
/Users/DDXQL/Documents/大学/硕士/代码/2.4.4/_pdata/fjsp
```

The frozen metadata identifies them as Behnke and Geiger (2012) instances, locally reformatted. Earlier provenance work compared their operation records with SchedulingLab commit `ac4c3402312bfbeafcf4472d78be567d4e6b46ab` after accounting for machine-index conventions.

## Counts

- train: 21
- validation: 11
- test: 28
- sanity input: `sample.fjsp`
- local files: 61

`fjsp_manifest.json` records the fixed order, partition and SHA-256 for every local file. During migration, source and copied files were checked byte-for-byte through SHA-256. Test files were only copied and checksummed; they were not parsed by the FJSP loader or evaluated.

## Redistribution

The current dataset redistribution license has not been confirmed. Consequently, `data/fjsp/*.fjsp` is ignored by Git. The hashes and metadata remain tracked so an authorized local copy can be restored and verified. Do not publish the instance files until their redistribution terms are confirmed.
