function initLightbox() {
  document.querySelectorAll('.md-typeset img:not(.no-zoom)').forEach(img => {

    img.style.cursor = 'pointer';
    img.onclick = () => {
      basicLightbox.create(`
        <img src="${img.src}" style="
            width: 50vw;
            height: auto;
            object-fit: contain;
        " />
      `).show();
    };
  });
}

document.addEventListener("DOMContentLoaded", initLightbox);
