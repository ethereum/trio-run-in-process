# Default number of seconds given to a child to reach the EXECUTING state before we yield in
# open_in_process(). Can be overwritten via the TRIO_RUN_IN_PROCESS_STARTUP_TIMEOUT
# environment variable.
STARTUP_TIMEOUT_SECONDS = 5

# The number of seconds that are given to a child process to exit after the
# parent process gets a KeyboardInterrupt/SIGINT-signal and sends a `SIGINT` to
# the child process. Can be overwritten via the TRIO_RUN_IN_PROCESS_SIGINT_TIMEOUT environment
# variable.
SIGINT_TIMEOUT_SECONDS = 2
