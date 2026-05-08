module.exports = {
  apps: [
    {
      name: "telegram-crm-bot",
      cwd: "/root/projects/telegram-crm-bot",
      script: "venv/bin/python",
      args: "bot.py",
      env: {
        PYTHONUNBUFFERED: "1",
      },
      log_file: "/root/projects/telegram-crm-bot/logs/combined.log",
      out_file: "/root/projects/telegram-crm-bot/logs/out.log",
      error_file: "/root/projects/telegram-crm-bot/logs/err.log",
      merge_logs: true,
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
    },
  ],
};
