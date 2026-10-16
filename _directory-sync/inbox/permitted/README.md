# Licensed datasets

Put a licensed establishment dataset here as CSV, with a `PROVENANCE.md`.
These files are git-ignored and are never committed, because this repository
is public.

`PROVENANCE.md` must contain:

```
Permission: <who granted it, reference, date>
Publication: permitted        # or: not permitted
```

If the licence does not permit publication, matched records are kept in
`state/private/`, which is also git-ignored. They are counted in the report but
never written to public files.

For the scheduled job, use repository secrets instead of committing files:

- `PERMITTED_DATASET_URL`: an HTTPS link to the CSV
- `PERMITTED_PROVENANCE`: the text of `PROVENANCE.md`
