document.addEventListener('DOMContentLoaded', function () {
    var select = document.getElementById('account_type');
    var passwordField = document.getElementById('password-field');

    function toggle() {
        passwordField.style.display = select.value === 'local' ? 'block' : 'none';
    }

    select.addEventListener('change', toggle);
    toggle();
});
