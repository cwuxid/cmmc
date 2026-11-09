from .cli import main

# Enables `python -m bailey_motion` when this package's parent is on sys.path.
# The process exit code distinguishes clearance, incomplete runs, and errors.
raise SystemExit(main())
