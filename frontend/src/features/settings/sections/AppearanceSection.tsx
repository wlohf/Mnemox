import { useRef, useState, type CSSProperties } from 'react'
import { ImagePlus, RotateCcw, Trash2 } from 'lucide-react'
import { Button, Slider, toast } from '../../../ui'
import { useThemeStore, type ThemeMode } from '../../../stores/themeStore'
import { uploadBackgroundImageStrict } from '../../../services/imageApi'
import { getApiErrorMessage, withAuthQuery } from '../../../services/apiClient'
import { Group, Row, Rows, settingsStyles as s } from '../SettingsDialog'

const THEMES: Array<{ value: ThemeMode; label: string; preview: Record<string, string> }> = [
  { value: 'warm', label: '浅色', preview: { '--p-side': '#eef0f5', '--p-canvas': '#f6f7fa', '--p-text': '#191e29', '--p-ink': '#284f88' } },
  { value: 'dark', label: '深色', preview: { '--p-side': '#0b0d12', '--p-canvas': '#101318', '--p-text': '#e7eaef', '--p-ink': '#8db3ea' } },
  {
    value: 'system',
    label: '跟随系统',
    preview: { '--p-side': 'linear-gradient(135deg,#eef0f5 50%,#0b0d12 50%)', '--p-canvas': 'linear-gradient(135deg,#f6f7fa 50%,#101318 50%)', '--p-text': '#7a808c', '--p-ink': '#5a82bd' },
  },
]

export function AppearanceSection() {
  const { mode, setMode, bgImage, bgOpacity, setBgImage, setBgOpacity, resetToDefault } = useThemeStore()
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)

  const upload = async (file: File) => {
    if (!file.type.startsWith('image/')) {
      toast.warning('请选择图片文件')
      return
    }
    setUploading(true)
    try {
      const res = await uploadBackgroundImageStrict(file)
      setBgImage(res.raw_url)
      toast.success('背景图已更新')
    } catch (e) {
      toast.error(getApiErrorMessage(e, '背景图上传失败'))
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      <Group title="主题">
        <div className={s.themes} role="radiogroup" aria-label="主题">
          {THEMES.map(t => (
            <button key={t.value} type="button" role="radio" aria-checked={mode === t.value} className={s.theme} onClick={() => setMode(t.value, { animate: true })}>
              <span className={s.themePreview} style={t.preview as CSSProperties} aria-hidden>
                <span />
                <span />
              </span>
              <span className={s.themeLabel}>{t.label}</span>
            </button>
          ))}
        </div>
      </Group>

      <Group title="背景图" desc="在工作区铺一张低透明度的图片。建议选择安静、低对比的照片，避免影响阅读。">
        <Rows>
          <Row label={bgImage ? '当前背景' : '未设置背景'} hint={bgImage ? '可以随时更换或移除' : '支持 PNG、JPG、WebP'}>
            {bgImage && <span className={s.bgPreview} style={{ backgroundImage: `url("${withAuthQuery(bgImage)}")` }} aria-hidden />}
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              hidden
              onChange={e => {
                const f = e.target.files?.[0]
                if (f) void upload(f)
                e.target.value = ''
              }}
            />
            <Button size="sm" icon={<ImagePlus />} loading={uploading} onClick={() => fileRef.current?.click()}>
              {bgImage ? '更换' : '上传图片'}
            </Button>
            {bgImage && (
              <Button size="sm" variant="ghost" icon={<Trash2 />} onClick={() => setBgImage(null)}>
                移除
              </Button>
            )}
          </Row>
          {bgImage && (
            <Row label="透明度" hint={`${Math.round(bgOpacity * 100)}%`}>
              <div style={{ width: 200 }}>
                <Slider ariaLabel="背景透明度" min={5} max={40} step={1} value={Math.round(bgOpacity * 100)} onValueChange={v => setBgOpacity(v / 100)} />
              </div>
            </Row>
          )}
        </Rows>
      </Group>

      <Group>
        <Button variant="ghost" size="sm" icon={<RotateCcw />} onClick={resetToDefault}>
          恢复默认外观
        </Button>
      </Group>
    </>
  )
}
