export const freshSession = () => globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
export const state = {session:sessionStorage.kzSession ||= freshSession(), request:{}, meta:{}, cart:[]};
export const modes = {smart:'Умный', fast:'Быстрый', naive:'Наивный'};
export const segments = {smb:'Малый бизнес',mid:'Средний бизнес',enterprise:'Крупный бизнес',gov:'Госсектор',edu:'Образование',individual:'Частный клиент'};
