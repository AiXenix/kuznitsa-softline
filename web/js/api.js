export async function api(url, body, options={}) {
  let response;
  try {
    response = await fetch(url, {...(body ? {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    } : {}), ...options});
  } catch { throw Error('Нет связи с сервером. Повторите попытку.'); }
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw Error(error?.error?.message || 'Не удалось загрузить данные.');
  }
  return response.status === 204 ? null : response.json();
}
