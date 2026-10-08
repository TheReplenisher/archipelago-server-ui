import { ActionIcon, useComputedColorScheme, useMantineColorScheme } from '@mantine/core'
import { IconMoon, IconSun } from '@tabler/icons-react'

export function ColorSchemeToggle() {
  const { setColorScheme } = useMantineColorScheme()
  const computed = useComputedColorScheme('dark', { getInitialValueInEffect: true })
  const next = computed === 'dark' ? 'light' : 'dark'

  return (
    <ActionIcon
      variant="default"
      size="lg"
      onClick={() => setColorScheme(next)}
      aria-label={`Switch to ${next} mode`}
    >
      {computed === 'dark' ? (
        <IconSun size={18} stroke={1.5} />
      ) : (
        <IconMoon size={18} stroke={1.5} />
      )}
    </ActionIcon>
  )
}
