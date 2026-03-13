document.addEventListener('DOMContentLoaded', function () {
    var dropZone = document.getElementById('drop-zone');
    var fileInput = document.getElementById('file-input');
    var statusDiv = document.getElementById('upload-status');

    if (!dropZone) { return; }

    // Make the zone clickable to open file picker
    dropZone.addEventListener('click', function () {
        fileInput.click();
    });

    // Prevent default browser handling for drag events
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(function (evt) {
        dropZone.addEventListener(evt, preventDefault, false);
        document.body.addEventListener(evt, preventDefault, false);
    });

    // Visual feedback
    ['dragenter', 'dragover'].forEach(function (evt) {
        dropZone.addEventListener(evt, function () {
            dropZone.classList.add('drag-over');
        }, false);
    });
    ['dragleave', 'drop'].forEach(function (evt) {
        dropZone.addEventListener(evt, function () {
            dropZone.classList.remove('drag-over');
        }, false);
    });

    // Handle dropped files
    dropZone.addEventListener('drop', function (e) {
        uploadFiles(e.dataTransfer.files);
    }, false);

    // Handle file input change (click-to-browse fallback)
    fileInput.addEventListener('change', function () {
        uploadFiles(this.files);
        this.value = '';
    });

    function preventDefault(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    function uploadFiles(files) {
        Array.prototype.forEach.call(files, uploadFile);
    }

    function uploadFile(file) {
        var csrfMeta = document.querySelector('meta[name="csrf-token"]');
        var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

        var formData = new FormData();
        formData.append('file', file);
        formData.append('csrf_token', csrfToken);

        showStatus('Uploading "' + file.name + '"…', 'info');

        fetch('/documents/upload', {
            method: 'POST',
            body: formData,
        })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (data.success) {
                    showStatus(data.message, 'success');
                    setTimeout(function () { window.location.reload(); }, 800);
                } else {
                    showStatus(data.message, 'error');
                }
            })
            .catch(function () {
                showStatus('Upload failed. Please try again.', 'error');
            });
    }

    function showStatus(message, type) {
        statusDiv.textContent = message;
        statusDiv.className = 'upload-status alert alert-' + type;
        statusDiv.style.display = 'block';
    }
});
