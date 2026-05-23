const TRAY_ICON_DATA_URL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAjElEQVR4nO3VUQqAIBCEYa/SPbtVB6znwm3HaSZRXPAlFv8vCCplpNn240ROt7AcwoYlEFWcQqjjTQhXHEK44ymiKyBafk52ObpPA6KL0b0qoOWNVIAbggGgswDzAdjn8wEU+wsw5r/ABogQDkA1nn0LyhMC/kC8xt0IKO5CNMXVCCqugHwOsxB52DkXmBWz1hDOxiQAAAAASUVORK5CYII='

function createTrayIcon(nativeImage) {
  const icon = nativeImage.createFromDataURL(TRAY_ICON_DATA_URL)

  if (!icon || icon.isEmpty()) {
    throw new Error('Failed to create tray icon')
  }

  return icon
}

module.exports = {
  TRAY_ICON_DATA_URL,
  createTrayIcon,
}
