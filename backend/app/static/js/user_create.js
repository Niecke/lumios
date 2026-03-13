document.addEventListener('DOMContentLoaded', function () {
    var radios = document.querySelectorAll('input[name="account_type"]');
    var passwordField = document.getElementById('password-field');

    radios.forEach(function (radio) {
        radio.addEventListener('change', function () {
            passwordField.style.display = this.value === 'local' ? 'block' : 'none';
        });
    });
});
