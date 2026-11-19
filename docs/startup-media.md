# Startup screen · 0.7.7

Original startup is the default. To remove an older installed animation, select **Keep original startup** and transfer the newly prepared dashboard. Legacy outputs are still recognized by exact regeneration.

**Still photo (PNG, JPEG, BMP).** The photo is fitted without cropping or distortion into a centered 192 × 256 box on the 240 × 320 LCD, with black margins. EXIF orientation is respected; transparency is composited over black. A flash-resident RGB565 bitmap is drawn on a child of the normal native welcome page. It follows the stock startup transition; there is no frame player, extra timer or fixed two-second delay for a photo.

**Prepared GIF import (experimental).** No converter is included. Prepare the file in your own editor before importing:

- Both the original GIF and the embedded native asset must be strictly smaller than 280,000 bytes.
- Width: 16–128 pixels, even. Height: 16–160 pixels.
- 2–20 frames; every frame must last 200–1,000 ms, at most 5 fps.
- Total duration: at most 4 seconds. Source loop metadata is ignored; the radio plays the sequence once.
- No imposed palette-color limit. The LCD represents colors in RGB565, with up to 65,536 native shades. This is a hardware format, not unrestricted 24-bit color.

The importer does not resize, recolor to a small palette, drop frames, change timing or export a converted GIF. It decodes GIF disposal/transparency and packages the existing frame pixels for the radio player; transparent areas display over black. Pixels are expressed in native RGB565. Animations containing at most 16 colors use the existing indexed path. More colorful animations use player v4 and direct RGB565 frames; multiple local GIF palettes are supported. A frame at the maximum size requires 40,960 bytes of mutable memory, compared with 10,240 for the older indexed format. Failed modeled allocations fall back to native startup, but real heap headroom remains unmeasured.

The existing player displays the source over a 240 × 275 region at y=22 using integer scaling; the source dimensions are not the physical LCD resolution. Prepare a matching aspect ratio if you want to avoid distortion. The preview reproduces the decoded colors, scaling and frame delays.

**Warning: GIFs can crash or freeze the transmitter, even when they meet every requirement. A freeze has already been reported.** These checks are application bounds, not a manufacturer guarantee. Keep the vehicle off during testing. If the transmitter freezes, reinstall a version with **Keep original startup** using the existing maintenance workflow. Do not interrupt an active firmware transfer. A photo uses the simpler native static display.

At step 4, select a local file and review the preview, then select **Use this photo** or **Embed this GIF**. Viewing a file alone does not apply it. Requirements and the warning are visible before and after import; on very small windows the requirements open from the **GIF requirements** button. No GIF preset is bundled.

**Français :** prépare ton GIF avant l’import : moins de 280 Ko, largeur paire entre 16 et 128 pixels, hauteur entre 16 et 160 pixels, 2 à 20 images, 200 à 1 000 ms par image et 4 secondes maximum. Aucune limite de palette n’est imposée ; les couleurs sont affichées dans le RGB565 natif de l’écran. L’application ne redimensionne pas le GIF et ne réduit pas sa palette. **Même conforme, un GIF peut faire planter ou figer la radio.** Si cela arrive, réinstalle un dashboard avec le démarrage d’origine.
