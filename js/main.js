// KORA — JS

// Toast notification
function showToast(msg) {
  let toast = document.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 3500);
}

// Notify modal
function openNotifyModal() {
  document.getElementById('notifyModal').classList.add('active');
}
function closeNotifyModal() {
  document.getElementById('notifyModal').classList.remove('active');
}
document.getElementById('notifyModal').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) closeNotifyModal();
});

// Form handlers
function handleNotify(e) {
  e.preventDefault();
  closeNotifyModal();
  showToast('¡Listo! Te avisamos cuando salgan los tickets. 🔥');
  e.target.reset();
}

function handleContact(e) {
  e.preventDefault();
  showToast('Mensaje enviado. Te respondemos pronto. ☀️');
  e.target.reset();
}

// Nav scroll effect
const nav = document.querySelector('.nav');
window.addEventListener('scroll', () => {
  if (window.scrollY > 60) {
    nav.style.padding = '14px 40px';
  } else {
    nav.style.padding = '20px 40px';
  }
});

// Burger menu (mobile)
const burger = document.querySelector('.nav-burger');
const navLinks = document.querySelector('.nav-links');
burger.addEventListener('click', () => {
  const isOpen = navLinks.style.display === 'flex';
  navLinks.style.display = isOpen ? 'none' : 'flex';
  navLinks.style.flexDirection = 'column';
  navLinks.style.position = 'absolute';
  navLinks.style.top = '70px';
  navLinks.style.left = '0';
  navLinks.style.right = '0';
  navLinks.style.background = 'rgba(10,10,10,0.98)';
  navLinks.style.padding = '20px 40px';
  navLinks.style.gap = '20px';
});

// Smooth scroll nav links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', (e) => {
    const target = document.querySelector(anchor.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (navLinks.style.display === 'flex') navLinks.style.display = 'none';
    }
  });
});

// Intersection Observer — fade in sections
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.style.opacity = '1';
      entry.target.style.transform = 'translateY(0)';
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.about-card, .artist-card, .event-item').forEach(el => {
  el.style.opacity = '0';
  el.style.transform = 'translateY(20px)';
  el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
  observer.observe(el);
});
