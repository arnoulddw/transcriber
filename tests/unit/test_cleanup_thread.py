import threading

from app.tasks import cleanup


def test_cleanup_loop_returns_promptly_when_stopped_during_startup_wait():
    stop = threading.Event()
    stop.set()

    # Without the stop event this would sleep 20s before its first cycle.
    finished = threading.Event()
    thread = threading.Thread(
        target=lambda: (cleanup.run_cleanup_task(object(), stop_event=stop), finished.set())
    )
    thread.start()
    thread.join(timeout=2)

    assert finished.is_set()


def test_cleanup_thread_exits_process_when_loop_dies(monkeypatch):
    exit_codes = []
    exited = threading.Event()

    def boom(app, *, stop_event):
        raise RuntimeError("unexpected")

    def fake_exit(code):
        exit_codes.append(code)
        exited.set()

    monkeypatch.setattr(cleanup, "run_cleanup_task", boom)
    monkeypatch.setattr(cleanup.os, "_exit", fake_exit)

    thread = cleanup.start_cleanup_thread(object(), threading.Event())
    thread.join(timeout=2)

    assert exited.is_set()
    assert exit_codes == [1]
    assert thread.daemon
