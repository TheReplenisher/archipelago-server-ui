import type { ConsoleCommand } from '../api/client'

/** One word for AP's console, which splits a command's words as a shell would (shlex):
 * quoted when it holds spaces, quotes or backslashes. */
export function quote(word: string): string {
  return /^[^\s"'\\]+$/.test(word) ? word : `"${word.replace(/["\\]/g, '\\$&')}"`
}

/** The console line for a command and its argument values. Trailing empty arguments are
 * left out. A raw command gets the rest of the line as it is, so nothing is quoted. */
export function buildLine(command: ConsoleCommand, values: string[]): string {
  const words = command.args.map((_, i) => (values[i] ?? '').trim())
  while (words.length > 0 && !words[words.length - 1]) words.pop()
  const args = command.raw ? words.filter(Boolean) : words.map((w) => (w ? quote(w) : '""'))
  return [`/${command.name}`, ...args].join(' ')
}
