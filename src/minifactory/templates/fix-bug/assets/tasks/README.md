# Bug reports for `minifactory run fix-bug`

One YAML file per bug (not needed for `minifactory ask`, which drafts the job from your sentence):

```yaml
repo: acme/todo_app          # GitHub owner/name; you need push access (the work goes to a branch + PR)
task: >
  Marking a todo as done on the detail screen throws "Null check operator used on a null value".
```
