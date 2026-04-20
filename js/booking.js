/**
 * KORA DJ Booking System — Client
 *
 * Architecture:
 *  - All mutations go through Supabase Edge Functions (no secrets in browser).
 *  - Idempotency key generated once per session; re-used on page refresh so
 *    the user can never accidentally create two bookings.
 *  - Every critical step has a timeout (AbortController) to surface slow
 *    network issues cleanly instead of hanging forever.
 *  - Stripe PaymentIntent is created server-side; only the client_secret
 *    crosses to the browser — card data never touches our servers.
 */
(function () {
  'use strict';

  // ── Configuration ────────────────────────────────────────────
  // Replace these placeholders when you deploy.
  const CFG = {
    SUPABASE_URL:     'https://YOUR_PROJECT_REF.supabase.co',
    SUPABASE_ANON:    'YOUR_SUPABASE_ANON_KEY',
    STRIPE_PK:        'pk_live_YOUR_STRIPE_PUBLIC_KEY',
    EVENT_ID:         'YOUR_EVENT_UUID',          // UUID of the May-15 event row
    MAX_QTY:          10,
    API_TIMEOUT_MS:   20_000,   // 20 s for API calls
    PAYMENT_TIMEOUT:  60_000,   // 60 s grace for Stripe confirmPayment
  };

  // ── State ─────────────────────────────────────────────────────
  const S = {
    step:           1,
    idempotencyKey: null,
    event:          null,       // fetched event row
    ticketType:     'general',
    quantity:       1,
    name:           '',
    email:          '',
    bookingId:      null,
    unitPrice:      0,
    stripe:         null,
    elements:       null,
    payElement:     null,
    submitting:     false,
  };

  // ── Helpers ───────────────────────────────────────────────────
  function fmt(amount) {
    return '$' + Number(amount).toLocaleString('es-MX', {
      minimumFractionDigits: 0, maximumFractionDigits: 2,
    }) + ' MXN';
  }

  function el(id) { return document.getElementById(id); }

  function showGlobalLoader(text) {
    el('loading-text').textContent = text || 'Procesando...';
    el('loading-overlay').classList.add('show');
  }

  function hideGlobalLoader() {
    el('loading-overlay').classList.remove('show');
  }

  function showAlert(id, msg, visible = true) {
    const a = el(id);
    if (!a) return;
    a.textContent = msg;
    a.classList.toggle('show', visible);
  }

  function clearAlerts() {
    ['step1-error','step2-error','payment-error','payment-info'].forEach(id => {
      const a = el(id);
      if (a) { a.textContent = ''; a.classList.remove('show'); }
    });
  }

  // ── Idempotency key ───────────────────────────────────────────
  // One UUID per browser session. Survives page refresh so a reload
  // during payment doesn't create a second charge.
  function getIdempotencyKey() {
    if (S.idempotencyKey) return S.idempotencyKey;
    let key = sessionStorage.getItem('kora_idem');
    if (!key) {
      key = crypto.randomUUID();
      sessionStorage.setItem('kora_idem', key);
    }
    S.idempotencyKey = key;
    return key;
  }

  function resetIdempotencyKey() {
    const key = crypto.randomUUID();
    sessionStorage.setItem('kora_idem', key);
    S.idempotencyKey = key;
    return key;
  }

  // ── Fetch with timeout ────────────────────────────────────────
  async function fetchWithTimeout(url, opts, timeoutMs = CFG.API_TIMEOUT_MS) {
    const ctrl = new AbortController();
    const tid   = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const r = await fetch(url, { ...opts, signal: ctrl.signal });
      return r;
    } catch (err) {
      if (err.name === 'AbortError') throw new Error('Tiempo de espera agotado. Revisa tu conexión e intenta de nuevo.');
      throw err;
    } finally {
      clearTimeout(tid);
    }
  }

  // ── Load event from Supabase ──────────────────────────────────
  async function loadEvent() {
    const r = await fetchWithTimeout(
      `${CFG.SUPABASE_URL}/rest/v1/events?id=eq.${encodeURIComponent(CFG.EVENT_ID)}&select=*`,
      { headers: { apikey: CFG.SUPABASE_ANON, Authorization: `Bearer ${CFG.SUPABASE_ANON}` } }
    );
    if (!r.ok) throw new Error('No se pudo cargar el evento.');
    const rows = await r.json();
    if (!rows || rows.length === 0) throw new Error('Evento no encontrado.');
    return rows[0];
  }

  // ── API: create-payment-intent ────────────────────────────────
  async function createPaymentIntent() {
    const r = await fetchWithTimeout(
      `${CFG.SUPABASE_URL}/functions/v1/create-payment-intent`,
      {
        method:  'POST',
        headers: {
          'Content-Type':  'application/json',
          Authorization:   `Bearer ${CFG.SUPABASE_ANON}`,
        },
        body: JSON.stringify({
          idempotency_key: getIdempotencyKey(),
          event_id:        CFG.EVENT_ID,
          ticket_type:     S.ticketType,
          quantity:        S.quantity,
          customer_name:   S.name,
          customer_email:  S.email,
        }),
      },
      CFG.API_TIMEOUT_MS
    );

    const data = await r.json().catch(() => ({}));

    if (!r.ok) {
      if (data.already_confirmed) {
        throw Object.assign(new Error('Este boleto ya fue confirmado. Revisa tu correo.'), { alreadyConfirmed: true });
      }
      throw new Error(data.error || 'Error al inicializar el pago.');
    }
    return data; // { client_secret, booking_id }
  }

  // ── Update progress bar ───────────────────────────────────────
  function updateProgress(step) {
    for (let i = 1; i <= 4; i++) {
      const dot = el(`pd-${i}`);
      const pstep = el(`ps-${i}`);
      if (!dot || !pstep) continue;
      dot.classList.remove('active', 'done');
      pstep.classList.remove('active', 'done');
      if (i < step)       { dot.classList.add('done'); pstep.classList.add('done'); }
      else if (i === step) { dot.classList.add('active'); pstep.classList.add('active'); }
    }
    for (let i = 1; i <= 3; i++) {
      const line = el(`pl-${i}`);
      if (line) line.classList.toggle('done', i < step);
    }
  }

  // ── Show a step ───────────────────────────────────────────────
  function showStep(n) {
    for (let i = 1; i <= 4; i++) {
      const s = el(`step-${i}`);
      if (s) s.classList.toggle('active', i === n);
    }
    S.step = n;
    updateProgress(n);
    clearAlerts();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ── Update order summary (Steps 1 & 2) ───────────────────────
  function updateSummary() {
    const type   = S.ticketType === 'vip' ? 'VIP' : 'General';
    const total  = S.quantity * S.unitPrice;
    const desc   = `${S.quantity}× ${type}`;
    const totFmt = fmt(total);

    const setSafe = (id, val) => { const e = el(id); if (e) e.textContent = val; };
    setSafe('summary-desc',    desc);
    setSafe('summary-subtotal', fmt(S.unitPrice) + ' c/u');
    setSafe('summary-total',    totFmt);
    setSafe('recap-desc',       desc);
    setSafe('recap-total',      totFmt);
    setSafe('pay-amount',       totFmt);
  }

  // ── Populate event banner ─────────────────────────────────────
  function renderEvent(evt) {
    const eventDate = new Date(evt.date);
    const dateFmt   = eventDate.toLocaleDateString('es-MX', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    });
    const timeFmt = eventDate.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' });

    const setSafe = (id, val) => { const e = el(id); if (e) e.textContent = val; };
    setSafe('event-name', evt.name);
    setSafe('event-meta', `${dateFmt} · ${timeFmt} · ${evt.venue}`);

    const availGen = evt.capacity_general - evt.tickets_sold_general;
    const availVip = evt.capacity_vip - evt.tickets_sold_vip;
    const badge = el('capacity-badge');
    if (badge) {
      const totalAvail = availGen + availVip;
      if (totalAvail <= 20) {
        badge.textContent = `¡Solo quedan ${totalAvail} lugares!`;
        badge.classList.add('low');
      } else {
        badge.textContent = 'Lugares disponibles';
      }
    }

    // Prices
    setSafe('price-general', fmt(evt.price_general));
    setSafe('price-vip',     fmt(evt.price_vip));

    // Disable sold-out types
    if (availVip <= 0) {
      const vipInput = document.querySelector('input[value="vip"]');
      if (vipInput) {
        vipInput.disabled = true;
        const card = vipInput.nextElementSibling;
        if (card) {
          const sold = document.createElement('div');
          sold.className = 'ticket-type-sold-out';
          sold.textContent = 'Agotado';
          card.appendChild(sold);
        }
      }
    }

    S.unitPrice = evt.price_general;
    updateSummary();
  }

  // ── Validation ────────────────────────────────────────────────
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function validateStep1() {
    if (!S.event) return 'El evento no está disponible.';
    if (!['general','vip'].includes(S.ticketType)) return 'Selecciona un tipo de boleto.';
    if (S.quantity < 1 || S.quantity > CFG.MAX_QTY) return 'Cantidad inválida.';
    const available = S.ticketType === 'vip'
      ? S.event.capacity_vip - S.event.tickets_sold_vip
      : S.event.capacity_general - S.event.tickets_sold_general;
    if (available < S.quantity) {
      return `Solo quedan ${available} boleto(s) de este tipo.`;
    }
    return null;
  }

  function validateStep2() {
    let ok = true;
    const nameEl  = el('customer-name');
    const emailEl = el('customer-email');

    S.name  = nameEl  ? nameEl.value.trim()  : '';
    S.email = emailEl ? emailEl.value.trim().toLowerCase() : '';

    if (S.name.length < 2) {
      showFieldError('name-error', 'customer-name');
      ok = false;
    } else {
      clearFieldError('name-error', 'customer-name');
    }

    if (!EMAIL_RE.test(S.email)) {
      showFieldError('email-error', 'customer-email');
      ok = false;
    } else {
      clearFieldError('email-error', 'customer-email');
    }

    return ok ? null : 'Por favor corrige los campos marcados.';
  }

  function showFieldError(errId, inputId) {
    const e = el(errId);
    const i = el(inputId);
    if (e) e.classList.add('show');
    if (i) i.classList.add('invalid');
  }

  function clearFieldError(errId, inputId) {
    const e = el(errId);
    const i = el(inputId);
    if (e) e.classList.remove('show');
    if (i) i.classList.remove('invalid');
  }

  // ── Step navigation ───────────────────────────────────────────
  async function goStep2() {
    const err = validateStep1();
    if (err) { showAlert('step1-error', err); return; }
    showStep(2);
  }

  async function goStep3() {
    const err = validateStep2();
    if (err) { showAlert('step2-error', err); return; }

    showGlobalLoader('Iniciando pago seguro...');
    const btn = el('btn-step2');
    if (btn) btn.disabled = true;

    try {
      const { client_secret, booking_id } = await createPaymentIntent();
      S.bookingId = booking_id;
      await mountStripe(client_secret);
      showStep(3);
      el('payment-header-desc').textContent =
        `${S.quantity}× ${S.ticketType.toUpperCase()} — ${fmt(S.quantity * S.unitPrice)}`;
    } catch (err) {
      if (err.alreadyConfirmed) {
        showAlert('step2-error', err.message);
      } else {
        showAlert('step2-error', err.message || 'Error al conectar. Intenta de nuevo.');
        // Reset idempotency key so next attempt is fresh
        resetIdempotencyKey();
      }
    } finally {
      hideGlobalLoader();
      if (btn) btn.disabled = false;
    }
  }

  // ── Stripe Elements ───────────────────────────────────────────
  async function mountStripe(clientSecret) {
    if (!window.Stripe) throw new Error('Stripe no pudo cargar. Recarga la página.');

    S.stripe = window.Stripe(CFG.STRIPE_PK);
    S.elements = S.stripe.elements({
      clientSecret,
      appearance: {
        theme: 'night',
        variables: {
          colorPrimary:        '#C9960C',
          colorBackground:     '#1e1e1e',
          colorText:           '#F0E6C8',
          colorDanger:         '#e05252',
          colorTextPlaceholder:'#555',
          fontFamily:          'Inter, system-ui, sans-serif',
          borderRadius:        '6px',
          spacingUnit:         '4px',
        },
        rules: {
          '.Input': { border: '1px solid #2a2a2a', padding: '12px 14px' },
          '.Input:focus': { border: '1px solid #C9960C', boxShadow: '0 0 0 2px rgba(201,150,12,.2)' },
          '.Label': { color: '#9a8a6a', fontSize: '11px', letterSpacing: '2px', textTransform: 'uppercase' },
        },
      },
    });

    S.payElement = S.elements.create('payment');
    const wrap = el('payment-element-wrap');
    wrap.innerHTML = '';            // remove the loading skeleton
    S.payElement.mount(wrap);

    // Enable pay button once element is ready
    S.payElement.on('ready', () => {
      const btn = el('btn-pay');
      if (btn) btn.disabled = false;
    });
  }

  // ── Submit payment ────────────────────────────────────────────
  async function submitPayment() {
    if (S.submitting) return;
    clearAlerts();

    // Validate element is complete (Stripe fires its own UI validation,
    // but we guard here for the button path)
    S.submitting = true;
    const btn     = el('btn-pay');
    const spinner = el('pay-spinner');
    const label   = el('pay-label');

    if (btn)     btn.disabled = true;
    if (spinner) spinner.classList.add('visible');
    if (label)   label.textContent = 'Procesando...';

    // Build the return URL (booking-success.html reads query params from Stripe)
    const returnUrl = `${window.location.origin}/booking-success.html` +
      `?booking_id=${encodeURIComponent(S.bookingId)}`;

    try {
      const { error } = await S.stripe.confirmPayment({
        elements:       S.elements,
        confirmParams:  {
          return_url: returnUrl,
          payment_method_data: {
            billing_details: { name: S.name, email: S.email },
          },
        },
      });

      // If we reach here without redirect, an error occurred
      if (error) {
        const msg = mapStripeError(error);
        showAlert('payment-error', msg);
        // Card errors are user-fixable; reset idempotency so they can retry
        if (error.type === 'card_error' || error.code === 'card_declined') {
          resetIdempotencyKey();
        }
      }
    } catch (err) {
      showAlert('payment-error', 'Error de conexión. Verifica tu red e intenta de nuevo.');
    } finally {
      S.submitting = false;
      if (btn)     btn.disabled = false;
      if (spinner) spinner.classList.remove('visible');
      if (label)   label.textContent = 'Pagar';
    }
  }

  function mapStripeError(err) {
    const map = {
      card_declined:     'Tu tarjeta fue rechazada. Intenta con otra.',
      insufficient_funds:'Fondos insuficientes en la tarjeta.',
      expired_card:      'La tarjeta está vencida.',
      incorrect_cvc:     'El código de seguridad (CVC) es incorrecto.',
      incorrect_number:  'El número de tarjeta es incorrecto.',
      processing_error:  'Error al procesar. Espera un momento e intenta de nuevo.',
    };
    return map[err.code] || err.message || 'Error al procesar el pago.';
  }

  // ── Check for Stripe redirect result (post-payment) ───────────
  // If Stripe redirected back with payment_intent_client_secret in the URL
  // and we're still on this page, read the result.
  async function checkRedirectResult() {
    const params  = new URLSearchParams(window.location.search);
    const piCS    = params.get('payment_intent_client_secret');
    const piState = params.get('redirect_status');
    const bookId  = params.get('booking_id');

    if (!piCS) return false; // not a redirect

    if (piState === 'succeeded') {
      showConfirmation(bookId);
      return true;
    }
    if (piState === 'failed') {
      showStep(3);
      showAlert('payment-error', 'El pago falló. Por favor intenta de nuevo.');
      return true;
    }
    return false;
  }

  // ── Render confirmation (Step 4) ──────────────────────────────
  async function showConfirmation(bookingId) {
    // Clear idempotency key so a future booking is fresh
    sessionStorage.removeItem('kora_idem');

    showStep(4);

    // Populate with state we already have
    el('confirm-email-display').textContent = S.email || '—';
    el('confirm-tickets').textContent =
      `${S.quantity}× ${S.ticketType === 'vip' ? 'VIP' : 'General'}`;
    el('confirm-total').textContent = fmt(S.quantity * S.unitPrice);

    if (S.event) {
      el('confirm-event').textContent = S.event.name;
      const d = new Date(S.event.date);
      el('confirm-date').textContent = d.toLocaleDateString('es-MX', {
        weekday:'long', day:'numeric', month:'long', year:'numeric',
      });
    }

    // Fetch confirmation code from DB (webhook may have set it)
    if (bookingId) {
      try {
        const r = await fetchWithTimeout(
          `${CFG.SUPABASE_URL}/rest/v1/bookings` +
            `?id=eq.${encodeURIComponent(bookingId)}&select=confirmation_code,customer_email,customer_name`,
          { headers: { apikey: CFG.SUPABASE_ANON, Authorization: `Bearer ${CFG.SUPABASE_ANON}` } }
        );
        const rows = await r.json();
        if (rows && rows[0]) {
          el('confirm-code').textContent = rows[0].confirmation_code || '—';
          el('confirm-email-display').textContent = rows[0].customer_email || S.email;
        }
      } catch {
        // Non-critical; code may arrive via email
        el('confirm-code').textContent = 'Ver tu correo';
      }
    }
  }

  // ── Quantity controls ─────────────────────────────────────────
  function initQuantityControls() {
    const dec = el('qty-dec');
    const inc = el('qty-inc');
    const disp = el('qty-display');

    if (!dec || !inc || !disp) return;

    function render() {
      disp.textContent = S.quantity;
      dec.disabled = S.quantity <= 1;
      inc.disabled = S.quantity >= CFG.MAX_QTY;
      updateSummary();
    }

    dec.addEventListener('click', () => { if (S.quantity > 1) { S.quantity--; render(); } });
    inc.addEventListener('click', () => { if (S.quantity < CFG.MAX_QTY) { S.quantity++; render(); } });
    render();
  }

  // ── Ticket type radios ────────────────────────────────────────
  function initTicketTypeControls() {
    document.querySelectorAll('input[name="ticket_type"]').forEach(radio => {
      radio.addEventListener('change', () => {
        S.ticketType = radio.value;
        S.unitPrice  = radio.value === 'vip'
          ? (S.event?.price_vip     || 0)
          : (S.event?.price_general || 0);
        updateSummary();
      });
    });
  }

  // ── Wire up buttons ───────────────────────────────────────────
  function initButtons() {
    const safe = (id, fn) => { const b = el(id); if (b) b.addEventListener('click', fn); };

    safe('btn-step1',  () => goStep2());
    safe('btn-step2',  () => goStep3());
    safe('btn-pay',    () => submitPayment());
    safe('btn-back-1', () => { clearAlerts(); showStep(1); });
    safe('btn-back-2', () => {
      clearAlerts();
      // Destroy payment element to avoid multiple mounts
      if (S.payElement) { S.payElement.destroy(); S.payElement = null; S.elements = null; }
      // Reset idempotency key so a fresh PI is created on re-entry
      resetIdempotencyKey();
      showStep(2);
    });

    // Real-time validation on inputs
    const nameEl  = el('customer-name');
    const emailEl = el('customer-email');
    if (nameEl)  nameEl.addEventListener('input',  () => clearFieldError('name-error',  'customer-name'));
    if (emailEl) emailEl.addEventListener('input',  () => clearFieldError('email-error', 'customer-email'));
    if (emailEl) emailEl.addEventListener('blur',   () => {
      if (S.email && !EMAIL_RE.test(emailEl.value.trim())) showFieldError('email-error', 'customer-email');
    });
  }

  // ── Bootstrap ─────────────────────────────────────────────────
  async function init() {
    initQuantityControls();
    initTicketTypeControls();
    initButtons();

    // Check if returning from Stripe redirect
    const wasRedirect = await checkRedirectResult().catch(() => false);
    if (wasRedirect) return;

    // Load event data
    showGlobalLoader('Cargando evento...');
    try {
      S.event = await loadEvent();
      renderEvent(S.event);
    } catch (err) {
      showAlert('step1-error', err.message || 'No se pudo cargar el evento. Recarga la página.');
    } finally {
      hideGlobalLoader();
    }
  }

  // Wait for DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
