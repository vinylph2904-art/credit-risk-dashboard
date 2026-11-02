const passwordInput = document.getElementById('password');
const passwordToggle = document.getElementById('toggle-password');
const loginForm = document.getElementById('login-form');
const loginSubmit = loginForm.querySelector('button[type=submit]');
const loginSubmitLabel = loginSubmit.querySelector('.login-submit-label');

passwordToggle.addEventListener('click', () => {
  const visible = passwordInput.type === 'password';
  passwordInput.type = visible ? 'text' : 'password';
  passwordToggle.textContent = visible ? 'Ẩn' : 'Hiện';
  passwordToggle.setAttribute('aria-pressed', String(visible));
  passwordToggle.setAttribute('aria-label', visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
});

loginForm.addEventListener('submit', () => {
  if (loginForm.checkValidity()) {
    loginSubmit.disabled = true;
    loginSubmitLabel.textContent = 'Đang đăng nhập…';
    loginForm.setAttribute('aria-busy', 'true');
  }
});

window.addEventListener('pageshow', () => {
  loginSubmit.disabled = false;
  loginSubmitLabel.textContent = 'Đăng nhập';
  loginForm.removeAttribute('aria-busy');
});
