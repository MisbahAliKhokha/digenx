# digenx

**Apna Digen agent CLI** — terminal se Digen AI agents se chat karo. 100% free, koi credit system nahi.

Digen ek AI video agent hai: aap brief do, wo finished video banata hai (short dramas, shorts, ads, AI avatar clips). Ye tool us se baat karne ka terminal client hai.

## Features

| Feature | Detail |
|---|---|
| **Chat** | Interactive chat, jawab streaming me aate hain |
| **Video length setting** | Jitni lambi video chahiye — `--duration` ya `/set duration` (koi limit nahi, Digen jitna allow kare) |
| **Frame size setting** | Koi bhi frame size — `--aspect 16:9` / `9:16` / `1:1` / `1920x1080` |
| **Workflows** | Available workflows ki list |
| **Sessions** | Conversations list, history dekho, delete karo, resume karo |
| **Image attach** | Chat me image bhejo (`/attach`) |
| **MCP server** | Claude Code, Cursor, Codex waghera se direct use |
| **Login** | Google se browser login, token save |

## Install

```bash
git clone https://github.com/MisbahAliKhokha/digenx.git
cd digenx
./install.sh
```

## Usage

```bash
digenx login                      # browser khulega, Google se login
digenx chat                       # chat shuru
digenx chat --duration 3600 --aspect 9:16   # 1 ghante ki video, vertical
digenx sessions                   # purani conversations
digenx history <id>               # ek conversation ki history
digenx delete <id>                # delete
digenx workflows                  # workflows dekho
digenx config set-duration 1800   # default: 30 min
digenx config set-aspect 16:9     # default frame size
```

### Chat ke andar commands

```
/new                  nayi conversation
/switch <id>          purani conversation kholo
/set duration <sec>   video ki lambai (seconds)
/set aspect <WxH>     frame size (16:9, 9:16, 1:1...)
/attach <path>        image bhejo
/history, /sessions, /workflow, /cancel, /confirm, /help, /quit
```

### MCP (AI tools ke liye)

```bash
claude mcp add --transport stdio --scope user digenx -- digenx-mcp
```

Tools: `digen_send`, `digen_poll`, `digen_confirm`, `digen_cancel`, `digen_list_workflows`, `digen_history`

## Free hai

Is tool me **koi credit system nahi** — free aur open. (Video banane ke liye Digen ka account chahiye, wo unki taraf se hai.)

## License

MIT
