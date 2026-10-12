from app.run_lock import RunLock


def test_try_acquire_succeeds_when_free():
    lock = RunLock()
    assert lock.try_acquire() is True
    assert lock.in_progress is True


def test_try_acquire_fails_when_already_held():
    lock = RunLock()
    assert lock.try_acquire() is True
    assert lock.try_acquire() is False
    assert lock.in_progress is True


def test_release_allows_reacquire():
    lock = RunLock()
    lock.try_acquire()
    lock.release()
    assert lock.in_progress is False
    assert lock.try_acquire() is True
