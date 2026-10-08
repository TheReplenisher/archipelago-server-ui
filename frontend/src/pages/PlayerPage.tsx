import { Stack, Text, Title } from '@mantine/core'

export function PlayerPage() {
  return (
    <Stack maw={960}>
      <Title order={2}>Player</Title>
      <Text c="dimmed">
        Log in with your slot name and the room password to see your items, locations and hints.
        Coming in Alpha 1.
      </Text>
    </Stack>
  )
}
