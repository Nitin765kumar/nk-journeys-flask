/* NK Journeys front end: small enhancements on top of server-rendered pages.
   Everything here is optional. The site still works with JavaScript turned off. */
(function () {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Google Fonts is loaded as a low-priority stylesheet and switched on here, so it never blocks the first paint. */
  $$('link[data-fonts]').forEach((link) => { link.media = 'all'; });

  /* ---------- Navigation: mobile menu and shadow after scrolling ---------- */
  const nav = $('.nav');
  const menuButton = $('.nav-btn');
  if (menuButton) {
    menuButton.addEventListener('click', () => {
      const open = $('#navl').classList.toggle('open');
      menuButton.setAttribute('aria-expanded', open);
    });
  }
  if (nav) {
    const onScroll = () => nav.classList.toggle('scrolled', window.scrollY > 24);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  /* ---------- Home hero: slow slideshow ---------- */
  const slides = $$('.hero .slide');
  if (slides.length > 1) {
    const caption = $('#slide-cap');
    let current = 0;
    setInterval(() => {
      if (reduceMotion) return;
      slides[current].classList.remove('on');
      current = (current + 1) % slides.length;
      slides[current].classList.add('on');
      if (caption) caption.textContent = slides[current].dataset.cap;
    }, 6000);
  }

  /* ---------- Fade-in on scroll ---------- */
  if ('IntersectionObserver' in window && !reduceMotion) {
    const items = $$('.card, .tile, .step, .why, .fact, .person, .cta, .vals .panel, .stat');
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        el.classList.add('in');
        observer.unobserve(el);
        // Remove the helper classes once played so hover effects are not affected.
        setTimeout(() => el.classList.remove('rv', 'in'), 1200);
      });
    }, { threshold: 0.12 });
    items.forEach((el, i) => {
      el.classList.add('rv');
      el.style.setProperty('--d', (i % 4) * 80 + 'ms');
      observer.observe(el);
    });
  }

  /* ---------- Small helpers driven by data attributes ---------- */
  $$('[data-autosubmit]').forEach((el) => el.addEventListener('change', () => el.form.submit()));
  $$('[data-print]').forEach((el) => el.addEventListener('click', () => window.print()));

  /* ---------- Booking page: live price and traveller name fields ---------- */
  const bookingForm = $('#booking-form');
  if (bookingForm) {
    const price = Number(bookingForm.dataset.price);
    const coupons = JSON.parse(bookingForm.dataset.coupons);
    const field = (name) => bookingForm.elements[name];
    // Same integer arithmetic as pricing.py, in paise, rounding half up.
    const percent = (amount, pct) => Math.floor((amount * pct + 50) / 100);
    const money = (paise) => '₹' + new Intl.NumberFormat('en-IN', {
      minimumFractionDigits: paise % 100 ? 2 : 0,
      maximumFractionDigits: 2,
    }).format(paise / 100);

    const updatePrice = () => {
      const adults = Number(field('adults').value);
      const children = Number(field('children').value);
      const unit = price * 100;
      const base = unit * adults + Math.floor((unit * children) / 2);
      const code = field('coupon').value.trim().toUpperCase();
      const discount = percent(base, coupons[code] || 0);
      const gst = percent(base - discount, 5);
      const total = base - discount + gst;
      const advance = $('input[name=pay_mode]:checked', bookingForm).value === 'advance';
      const values = { base, discount, gst, total, pay_now: advance ? percent(total, 30) : total };
      $$('[data-q]').forEach((el) => { el.textContent = money(values[el.dataset.q]); });
      $('[data-row=discount]').hidden = discount === 0;
      const message = $('#coupon-msg');
      if (!code) message.textContent = '';
      else message.textContent = coupons[code] ? `Coupon applied: ${coupons[code]}% off the trip fare.` : 'That code is not valid. Try NKJ10 in this demo.';
    };

    const updateTravellers = () => {
      const total = Number(field('adults').value) + Number(field('children').value) - 1;
      const box = $('#others');
      const old = $$('input[name=traveller]', box).map((input) => input.value);
      box.replaceChildren();
      if (total < 1) return;
      const heading = document.createElement('h3');
      heading.textContent = 'Other travellers';
      const row = document.createElement('div');
      row.className = 'row';
      for (let i = 0; i < total; i++) {
        const wrap = document.createElement('div');
        wrap.className = 'f';
        const label = document.createElement('label');
        label.htmlFor = 't' + i;
        label.textContent = `Traveller ${i + 2} full name`;
        const input = document.createElement('input');
        input.id = 't' + i;
        input.name = 'traveller';
        input.value = old[i] || '';
        wrap.append(label, input);
        row.append(wrap);
      }
      box.append(heading, row);
    };

    ['adults', 'children'].forEach((name) => field(name).addEventListener('change', () => { updateTravellers(); updatePrice(); }));
    field('coupon').addEventListener('input', updatePrice);
    $$('input[name=pay_mode]', bookingForm).forEach((el) => el.addEventListener('change', updatePrice));
    updatePrice();
  }

  /* ---------- Payment page: method tabs, card formatting, processing screen ---------- */
  const tabs = $$('.tab');
  if (tabs.length) {
    const panes = $$('.pane');
    tabs.forEach((tab) => tab.addEventListener('click', () => {
      tabs.forEach((t) => t.setAttribute('aria-selected', t === tab));
      panes.forEach((pane) => { pane.hidden = pane.dataset.pane !== tab.dataset.tab; });
    }));

    const number = $('#card_number');
    if (number) number.addEventListener('input', () => {
      number.value = number.value.replace(/\D/g, '').slice(0, 16).replace(/(.{4})/g, '$1 ').trim();
    });
    const expiry = $('#card_expiry');
    if (expiry) expiry.addEventListener('input', () => {
      const digits = expiry.value.replace(/\D/g, '').slice(0, 4);
      expiry.value = digits.length > 2 ? digits.slice(0, 2) + '/' + digits.slice(2) : digits;
    });

    // Show the "processing" screen briefly, but only when the form is filled in.
    const overlay = $('#processing');
    panes.forEach((pane) => pane.addEventListener('submit', (event) => {
      const filled = $$('input:not([type=hidden]), select', pane).every((el) => el.value.trim() !== '');
      if (!filled || pane.dataset.go) return;
      event.preventDefault();
      pane.dataset.go = '1';
      overlay.classList.add('on');
      setTimeout(() => pane.submit(), 1600);
    }));
  }
})();
