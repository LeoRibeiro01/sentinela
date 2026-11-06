(() => {
  const $ = (id) => document.getElementById(id);
  const ipInput = $('esp32-ip');
  const connectButton = $('connect-button');
  const root = document.documentElement;
  let baseUrl = localStorage.getItem('sentinela-esp32-url') || '';
  let pollTimer = null;

  if (baseUrl) ipInput.value = baseUrl.replace(/^https?:\/\//i, '').replace(/\/$/, '');

  function setConnection(connected, message) {
    $('connection-status').textContent = connected ? 'Conectado' : 'Desconectado';
    $('connection-status').className = `text-2xl font-bold ${connected ? 'text-teal-700 dark:text-teal-300' : 'text-slate-700 dark:text-slate-200'}`;
    $('connection-dot').className = `h-3 w-3 rounded-full ${connected ? 'bg-teal-500 shadow-[0_0_0_4px_rgba(20,184,166,.12)]' : 'bg-slate-300 dark:bg-slate-600'}`;
    $('last-update').textContent = message;
    $('turn-on').disabled = !connected;
    $('turn-off').disabled = !connected;
  }

  function normalizeAddress(value) {
    const candidate = value.trim().replace(/\/$/, '');
    if (!candidate) throw new Error('Informe o endereço IP do ESP32.');
    const url = new URL(/^https?:\/\//i.test(candidate) ? candidate : `http://${candidate}`);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('Use um endereço HTTP válido.');
    return url.origin;
  }

  async function request(path) {
    const response = await fetch(`${baseUrl}${path}`, { method: 'GET', cache: 'no-store' });
    if (!response.ok) throw new Error(`O ESP32 respondeu com HTTP ${response.status}.`);
    return response;
  }

  async function refreshStatus() {
    if (!baseUrl) return;
    try {
      const response = await request('/status');
      const data = await response.json();
      const value = Number(data.sensor);
      if (!Number.isFinite(value)) throw new Error('Resposta inválida do sensor.');
      $('sensor-value').textContent = String(value);
      $('sensor-bar').style.width = `${Math.max(0, Math.min(100, value / 4095 * 100))}%`;
      const isOn = typeof data.atuador_on === 'boolean' ? data.atuador_on : data.atuador === 'ligado';
      $('actuator-pill').textContent = isOn ? 'Ligado' : 'Desligado';
      $('actuator-pill').className = `rounded-full px-2.5 py-1 text-xs font-semibold ${isOn ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`;
      setConnection(true, `Última atualização às ${new Date().toLocaleTimeString('pt-BR')}`);
    } catch (error) {
      setConnection(false, error.message || 'Não foi possível acessar o ESP32.');
    }
  }

  async function connect() {
    try {
      baseUrl = normalizeAddress(ipInput.value);
      ipInput.value = baseUrl.replace(/^https?:\/\//, '');
      localStorage.setItem('sentinela-esp32-url', baseUrl);
      if (pollTimer) clearInterval(pollTimer);
      await refreshStatus();
      pollTimer = setInterval(refreshStatus, 2000);
    } catch (error) {
      setConnection(false, error.message);
    }
  }

  async function setActuator(state) {
    if (!baseUrl) return;
    try {
      await request(`/atuador?estado=${state}`);
      await refreshStatus();
    } catch (error) {
      setConnection(false, error.message || 'Falha ao enviar comando.');
    }
  }

  connectButton.addEventListener('click', connect);
  ipInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') connect(); });
  $('turn-on').addEventListener('click', () => setActuator('on'));
  $('turn-off').addEventListener('click', () => setActuator('off'));
  $('theme-toggle').addEventListener('click', () => {
    root.classList.toggle('dark');
    localStorage.setItem('sentinela-dark-mode', root.classList.contains('dark') ? 'on' : 'off');
  });
  if (localStorage.getItem('sentinela-dark-mode') === 'on') root.classList.add('dark');
  if (baseUrl) connect();
})();
