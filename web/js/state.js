export const freshSession = () => globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
export const state = {session:sessionStorage.kzSession ||= freshSession(), request:{}, meta:{}, cart:[]};
