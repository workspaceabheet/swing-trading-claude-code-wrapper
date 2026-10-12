// Tiny fetch wrapper: JSON in/out, non-2xx throws an Error with `.status`.
// No auth/token header needed -- this app only binds to 127.0.0.1.
async function apiFetch(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });

  let data = null;
  try {
    data = await res.json();
  } catch (err) {
    data = null;
  }

  if (!res.ok) {
    const error = new Error((data && data.error) || `Request failed: ${res.status}`);
    error.status = res.status;
    error.body = data;
    throw error;
  }

  return data;
}
