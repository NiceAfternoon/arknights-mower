function initLightbox() {
  document.querySelectorAll('.md-typeset img:not(.no-zoom)').forEach(img => {
    img.style.cursor = 'pointer';

    img.onclick = () => {
      basicLightbox.create(`
        <img src="${img.src}" style="
          max-height: 90vh;
          max-width: 90vw;
        " />
      `).show();
    };
  });
}

document.addEventListener("DOMContentLoaded", initLightbox);
