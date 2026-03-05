// ===== PRODUCT DATA =====
const products = [
  // --- BALL BOXES ---
  {
    id: 1, category: 'box',
    name: 'FUERTE Box 40+ (6 шт)',
    desc: 'Набор из 6 мячей 40+ мм для тренировок и соревнований. Бесшовная конструкция.',
    price: 890, oldPrice: 1100,
    badge: 'Хит продаж',
    stars: 5,
    visual: 'box', icon: 'FUERTE'
  },
  {
    id: 2, category: 'box',
    name: 'FUERTE Box 44 (6 шт)',
    desc: 'Набор мячей увеличенного диаметра 44 мм. Идеально для начинающих игроков.',
    price: 750, oldPrice: null,
    badge: null,
    stars: 4,
    visual: 'box', icon: 'FUERTE'
  },
  {
    id: 3, category: 'box',
    name: 'FUERTE Box 55 (6 шт)',
    desc: 'Большие мячи 55 мм для настольного тенниса. Увеличенный размер для специальных тренировок.',
    price: 950, oldPrice: null,
    badge: 'Новинка',
    stars: 5,
    visual: 'box', icon: 'FUERTE'
  },

  // --- INDIVIDUAL BALLS ---
  {
    id: 4, category: 'balls',
    name: 'FUERTE 40+ ★★★',
    desc: 'Профессиональный мяч 40+ мм, 3 звезды. Одобрен ITTF. Цвет: белый.',
    price: 190, oldPrice: null,
    badge: 'ITTF',
    stars: 5,
    visual: 'white', icon: '40'
  },
  {
    id: 5, category: 'balls',
    name: 'FUERTE 40+ Training',
    desc: 'Тренировочный мяч 40+ мм. Повышенная прочность. Цвет: жёлтый.',
    price: 120, oldPrice: null,
    badge: null,
    stars: 4,
    visual: 'yellow', icon: '40'
  },
  {
    id: 6, category: 'balls',
    name: 'FUERTE 44 мм',
    desc: 'Мяч увеличенного диаметра 44 мм. Отлично подходит для детских секций.',
    price: 140, oldPrice: 170,
    badge: 'Скидка',
    stars: 4,
    visual: 'white', icon: '44'
  },
  {
    id: 7, category: 'balls',
    name: 'FUERTE 55 мм',
    desc: 'Крупный мяч 55 мм для развивающих упражнений и реабилитации.',
    price: 160, oldPrice: null,
    badge: null,
    stars: 4,
    visual: 'yellow', icon: '55'
  },

  // --- RACKETS ---
  {
    id: 8, category: 'racket',
    name: 'FUERTE Pro Carbon',
    desc: 'Профессиональная ракетка с карбоновым основанием. 7 слоёв. Атакующий стиль.',
    price: 4500, oldPrice: 5200,
    badge: 'Топ',
    stars: 5,
    visual: 'racket', icon: '🏓'
  },
  {
    id: 9, category: 'racket',
    name: 'FUERTE Allround',
    desc: 'Универсальная ракетка для любителей. 5 слоёв дерева. Отличный контроль мяча.',
    price: 2800, oldPrice: null,
    badge: null,
    stars: 5,
    visual: 'racket', icon: '🏓'
  },
  {
    id: 10, category: 'racket',
    name: 'FUERTE Junior',
    desc: 'Детская ракетка с укороченной ручкой. Лёгкий вес. Для детей от 6 лет.',
    price: 1500, oldPrice: null,
    badge: null,
    stars: 4,
    visual: 'racket', icon: '🏓'
  },
  {
    id: 11, category: 'racket',
    name: 'FUERTE Defence',
    desc: 'Защитная ракетка с увеличенным контролем. Идеальна для оборонительного стиля.',
    price: 3200, oldPrice: 3800,
    badge: 'Скидка',
    stars: 5,
    visual: 'racket', icon: '🏓'
  },

  // --- ACCESSORIES ---
  {
    id: 12, category: 'accessory',
    name: 'Чехол FUERTE Pro',
    desc: 'Жёсткий чехол для 1 ракетки с карманом для мячей. Водоотталкивающий материал.',
    price: 980, oldPrice: null,
    badge: null,
    stars: 5,
    visual: 'accessory', icon: '👜'
  },
  {
    id: 13, category: 'accessory',
    name: 'Сетка FUERTE Clip-On',
    desc: 'Сетка с быстрым креплением на любой стол. Регулируемая высота и натяжение.',
    price: 1350, oldPrice: 1600,
    badge: 'Скидка',
    stars: 4,
    visual: 'accessory', icon: '🥅'
  },
  {
    id: 14, category: 'accessory',
    name: 'Накладка FUERTE Spin',
    desc: 'Накладка с максимальным вращением. Толщина губки 2.0 мм. Для продвинутых.',
    price: 2200, oldPrice: null,
    badge: 'Новинка',
    stars: 5,
    visual: 'accessory', icon: '🔴'
  },
  {
    id: 15, category: 'accessory',
    name: 'Очиститель накладок',
    desc: 'Спрей для ухода за накладками ракетки. Сохраняет липкость и продлевает срок службы.',
    price: 450, oldPrice: null,
    badge: null,
    stars: 4,
    visual: 'accessory', icon: '✨'
  },
  {
    id: 16, category: 'accessory',
    name: 'Обмотка для ручки',
    desc: 'Антискользящая обмотка для ручки ракетки. 3 штуки в упаковке.',
    price: 380, oldPrice: null,
    badge: null,
    stars: 4,
    visual: 'accessory', icon: '🎾'
  },
];

// ===== STATE =====
let cart = JSON.parse(localStorage.getItem('fuerte_cart') || '[]');
let activeFilter = 'all';

// ===== DOM ELEMENTS =====
const productsGrid = document.getElementById('productsGrid');
const cartBtn = document.getElementById('cartBtn');
const cartCount = document.getElementById('cartCount');
const cartDrawer = document.getElementById('cartDrawer');
const cartBody = document.getElementById('cartBody');
const cartFooter = document.getElementById('cartFooter');
const cartTotal = document.getElementById('cartTotal');
const cartClose = document.getElementById('cartClose');
const overlay = document.getElementById('overlay');
const burgerBtn = document.getElementById('burgerBtn');
const nav = document.querySelector('.nav');
const checkoutBtn = document.getElementById('checkoutBtn');
const modalOverlay = document.getElementById('modalOverlay');
const modalClose = document.getElementById('modalClose');
const orderForm = document.getElementById('orderForm');
const modalTitle = document.getElementById('modalTitle');
const modalContent = document.getElementById('modalContent');

// ===== RENDER PRODUCTS =====
function renderProducts() {
  const filtered = activeFilter === 'all'
    ? products
    : products.filter(p => p.category === activeFilter);

  productsGrid.innerHTML = filtered.map(p => {
    let visualHTML = '';
    if (p.visual === 'box') {
      visualHTML = `<div class="product-card__visual product-card__visual--box">${p.icon}</div>`;
    } else if (p.visual === 'racket') {
      visualHTML = `<div class="product-card__visual product-card__visual--racket">${p.icon}</div>`;
    } else if (p.visual === 'accessory') {
      visualHTML = `<div class="product-card__visual product-card__visual--accessory">${p.icon}</div>`;
    } else {
      const colorClass = p.visual === 'yellow' ? 'product-card__visual--yellow' : 'product-card__visual--white';
      visualHTML = `<div class="product-card__visual ${colorClass}">${p.icon}</div>`;
    }

    const categoryLabels = { balls: 'Мячи', box: 'Наборы', racket: 'Ракетки', accessory: 'Аксессуары' };
    const starsHTML = '★'.repeat(p.stars) + '☆'.repeat(5 - p.stars);
    const oldPriceHTML = p.oldPrice ? `<span class="product-card__old-price">${p.oldPrice.toLocaleString()} ₽</span>` : '';
    const badgeHTML = p.badge ? `<span class="product-card__badge">${p.badge}</span>` : '';

    return `
      <div class="product-card" data-id="${p.id}">
        <div class="product-card__img">
          ${badgeHTML}
          ${visualHTML}
        </div>
        <div class="product-card__body">
          <div class="product-card__category">${categoryLabels[p.category]}</div>
          <div class="product-card__stars">${starsHTML}</div>
          <div class="product-card__name">${p.name}</div>
          <div class="product-card__desc">${p.desc}</div>
          <div class="product-card__footer">
            <div>
              <span class="product-card__price">${p.price.toLocaleString()} ₽</span>
              ${oldPriceHTML}
            </div>
            <button class="btn btn--primary btn--sm add-to-cart" data-id="${p.id}">В корзину</button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  // Attach event listeners
  document.querySelectorAll('.add-to-cart').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      addToCart(Number(btn.dataset.id));
    });
  });
}

// ===== CART FUNCTIONS =====
function addToCart(productId) {
  const existing = cart.find(item => item.id === productId);
  if (existing) {
    existing.qty += 1;
  } else {
    cart.push({ id: productId, qty: 1 });
  }
  saveCart();
  updateCartUI();
  openCart();
}

function removeFromCart(productId) {
  cart = cart.filter(item => item.id !== productId);
  saveCart();
  updateCartUI();
}

function changeQty(productId, delta) {
  const item = cart.find(i => i.id === productId);
  if (!item) return;
  item.qty += delta;
  if (item.qty <= 0) {
    removeFromCart(productId);
    return;
  }
  saveCart();
  updateCartUI();
}

function saveCart() {
  localStorage.setItem('fuerte_cart', JSON.stringify(cart));
}

function getTotal() {
  return cart.reduce((sum, item) => {
    const product = products.find(p => p.id === item.id);
    return sum + (product ? product.price * item.qty : 0);
  }, 0);
}

function updateCartUI() {
  const totalItems = cart.reduce((sum, item) => sum + item.qty, 0);
  cartCount.textContent = totalItems;
  cartCount.style.display = totalItems > 0 ? 'flex' : 'none';

  if (cart.length === 0) {
    cartBody.innerHTML = '<p class="cart-empty">Корзина пуста</p>';
    cartFooter.style.display = 'none';
    return;
  }

  cartFooter.style.display = 'block';
  cartTotal.textContent = getTotal().toLocaleString();

  cartBody.innerHTML = cart.map(item => {
    const p = products.find(pr => pr.id === item.id);
    if (!p) return '';
    let emoji = '';
    if (p.visual === 'box') emoji = '📦';
    else if (p.visual === 'racket') emoji = '🏓';
    else if (p.visual === 'accessory') emoji = p.icon;
    else emoji = p.visual === 'yellow' ? '🟡' : '⚪';

    return `
      <div class="cart-item">
        <div class="cart-item__visual">${emoji}</div>
        <div class="cart-item__info">
          <div class="cart-item__name">${p.name}</div>
          <div class="cart-item__price">${p.price.toLocaleString()} ₽</div>
          <button class="cart-item__remove" data-remove="${p.id}">Удалить</button>
        </div>
        <div class="cart-item__controls">
          <button class="cart-item__qty-btn" data-minus="${p.id}">−</button>
          <span class="cart-item__qty">${item.qty}</span>
          <button class="cart-item__qty-btn" data-plus="${p.id}">+</button>
        </div>
      </div>
    `;
  }).join('');

  // Cart event listeners
  cartBody.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', () => removeFromCart(Number(btn.dataset.remove)));
  });
  cartBody.querySelectorAll('[data-minus]').forEach(btn => {
    btn.addEventListener('click', () => changeQty(Number(btn.dataset.minus), -1));
  });
  cartBody.querySelectorAll('[data-plus]').forEach(btn => {
    btn.addEventListener('click', () => changeQty(Number(btn.dataset.plus), 1));
  });
}

// ===== CART DRAWER TOGGLE =====
function openCart() {
  cartDrawer.classList.add('open');
  overlay.classList.add('active');
}
function closeCart() {
  cartDrawer.classList.remove('open');
  overlay.classList.remove('active');
}

cartBtn.addEventListener('click', openCart);
cartClose.addEventListener('click', closeCart);
overlay.addEventListener('click', closeCart);

// ===== TABS =====
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('tab--active'));
    tab.classList.add('tab--active');
    activeFilter = tab.dataset.filter;
    renderProducts();
  });
});

// ===== BURGER MENU =====
burgerBtn.addEventListener('click', () => {
  nav.classList.toggle('nav--mobile');
});

// Close mobile nav on link click
document.querySelectorAll('.nav__link').forEach(link => {
  link.addEventListener('click', () => {
    nav.classList.remove('nav--mobile');
  });
});

// ===== CHECKOUT =====
checkoutBtn.addEventListener('click', () => {
  closeCart();
  modalOverlay.classList.add('active');
  modalTitle.textContent = 'Оформление заказа';
  modalContent.innerHTML = `
    <form id="orderForm">
      <label class="form-group">
        <span>Имя</span>
        <input type="text" name="name" required placeholder="Ваше имя">
      </label>
      <label class="form-group">
        <span>Телефон</span>
        <input type="tel" name="phone" required placeholder="+7 (___) ___-__-__">
      </label>
      <label class="form-group">
        <span>Email</span>
        <input type="email" name="email" required placeholder="email@example.com">
      </label>
      <label class="form-group">
        <span>Адрес доставки</span>
        <input type="text" name="address" required placeholder="Город, улица, дом">
      </label>
      <div style="margin: 20px 0; padding: 16px; background: var(--gray-50); border-radius: var(--radius-sm);">
        <strong>Итого: ${getTotal().toLocaleString()} ₽</strong>
      </div>
      <button type="submit" class="btn btn--primary btn--full">Подтвердить заказ</button>
    </form>
  `;
  document.getElementById('orderForm').addEventListener('submit', handleOrder);
});

function handleOrder(e) {
  e.preventDefault();
  modalTitle.textContent = '';
  modalContent.innerHTML = `
    <div class="success-msg">
      <div class="success-msg__icon">&#10004;&#65039;</div>
      <div class="success-msg__text">Заказ оформлен!</div>
      <div class="success-msg__sub">Мы свяжемся с вами в ближайшее время для подтверждения заказа.</div>
    </div>
  `;
  cart = [];
  saveCart();
  updateCartUI();
  setTimeout(() => {
    modalOverlay.classList.remove('active');
  }, 3000);
}

modalClose.addEventListener('click', () => {
  modalOverlay.classList.remove('active');
});
modalOverlay.addEventListener('click', (e) => {
  if (e.target === modalOverlay) modalOverlay.classList.remove('active');
});

// ===== INIT =====
renderProducts();
updateCartUI();
