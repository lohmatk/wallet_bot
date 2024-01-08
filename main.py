#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pathlib
import tempfile
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, ContextTypes, \
    CallbackContext
from telegram import Chat, InlineKeyboardMarkup, Update, InlineKeyboardButton
import os
import re
from loguru import logger
import sqlite3
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

import calendar


bot_name = 'Ботик'
prod = 'TBOT_PROD' in os.environ and os.environ['TBOT_PROD'] == '1'
LOGNAME = 'tbot.log' if prod else 'tbot_dev.log'
DBFILE = 'tbot.sqlite' if prod else 'tbot_dev.sqlite'
DAILY_TARGET = 5000
tmp_path = tempfile.gettempdir() + '/tmp.png'

logger.add(LOGNAME, rotation="1 day")


def to_json_string(update):
    res = str(update).replace("'", '"').replace('True', 'true').replace('False', 'false')
    return res


def start(update: Update, context: CallbackContext):
    update.message.reply_text('Started!')


def help(update: Update, context: CallbackContext):
    update.message.reply_text('God will help!')


def error(update, error):
    logger.warning(f'Update "{update}" caused error "{error}"')


def reply(update, reply_text):
    update.message.reply_text(reply_text)
    oneline_reply = reply_text.replace('\n', '\\n')
    logger.info(f"Reply: {oneline_reply}")


def balance_text():
    dt = datetime.now()
    week_start = dt - timedelta(days=dt.weekday())
    con = sqlite3.connect(DBFILE)
    users = con.execute(f'SELECT DISTINCT(user) FROM spendings WHERE user IS NOT NULL').fetchall()
    users = [x[0] for x in users]
    users_count = len(users)

    dt = datetime.now()
    week_start = dt - timedelta(days=dt.weekday())
    month_tot_sum = con.execute(
        f"select sum(val) from spendings where ts >= '{dt.year}-{dt.month:02}-01' and ts < '{dt.year}-{dt.month:02}-32';").fetchone()[
                        0] or 0
    week_tot_sum = con.execute(
        f"select sum(val) from spendings where ts >= '{dt.year}-{week_start.month:02}-{week_start.day:02}';").fetchone()[
                       0] or 0
    day_tot_sum = \
        con.execute(f"select sum(val) from spendings where ts >= '{dt.year}-{dt.month:02}-{dt.day:02}';").fetchone()[0] or 0

    query_start = 'select sum(val) from spendings'
    month_cond = f"ts >= '{dt.year}-{dt.month:02}-01' and ts < '{dt.year}-{dt.month:02}-32'"
    week_cond = f"ts >= '{dt.year}-{week_start.month:02}-{week_start.day:02}'"
    day_cond = f"ts >= '{dt.year}-{dt.month:02}-{dt.day:02}'"

    # splitted spendings
    user_cond = 'user = :user'
    month_shared = con.execute(f"{query_start} WHERE {month_cond} AND user IS NULL;").fetchone()[0] or 0
    week_shared = con.execute(f"{query_start} WHERE {week_cond} AND user IS NULL;").fetchone()[0] or 0
    day_shared = con.execute(f"{query_start} WHERE {day_cond} AND user IS NULL;").fetchone()[0] or 0
    month_shared, week_shared, day_shared = month_shared / users_count, week_shared / users_count, day_shared / users_count

    user_spendings = []
    user_diff = []
    user_daily_target = DAILY_TARGET / users_count
    for user in users:
        month_sum = con.execute(f"{query_start} WHERE {month_cond} AND {user_cond};", {'user': user}).fetchone()[0] or 0
        week_sum = con.execute(f"{query_start} WHERE {week_cond} AND {user_cond};", {'user': user}).fetchone()[0] or 0
        day_sum = con.execute(f"{query_start} WHERE {day_cond} AND {user_cond};", {'user': user}).fetchone()[0] or 0
        day_sum, week_sum, month_sum = day_sum + day_shared, week_sum + week_shared, month_sum + month_shared
        user_spendings.append(f'{user}: {day_sum:.1f} / {week_sum:.1f} / {month_sum:.1f}')

        day_diff = user_daily_target - day_sum
        week_diff = user_daily_target * 7 - week_sum
        month_diff = user_daily_target * calendar.monthrange(dt.year, dt.month)[1] - month_sum
        user_diff.append(f'{user}: {day_diff:.1f} / {week_diff:.1f} / {month_diff:.1f}')

    caption = 'Расходы: день / неделя / месяц'
    caption += f'\nОбщие: {day_tot_sum:.1f} / {week_tot_sum:.1f} / {month_tot_sum:.1f}'
    for x in user_spendings:
        caption += '\n' + x

    caption += '\n\nОстаток: день / неделя / месяц'
    day_diff = DAILY_TARGET - day_tot_sum
    week_diff = DAILY_TARGET * 7 - week_tot_sum
    month_diff = DAILY_TARGET * calendar.monthrange(dt.year, dt.month)[1] - month_tot_sum
    caption += f'\nОбщие: {day_diff:.1f} / {week_diff:.1f} / {month_diff:.1f}'
    for x in user_diff:
        caption += '\n' + x

    return caption


def button(update: Update, context):
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    action, row_id = query.data.split()
    query.answer()
    if action == 'split':
        con = sqlite3.connect(DBFILE)
        con.execute(f'UPDATE spendings SET user = :user WHERE id = :id', {'user': None, 'id': row_id})
        con.commit()
        query.edit_message_text(text=f"{update.effective_message.text}\nРазделено поровну")
        update.effective_message.reply_text(balance_text())


def handle_message(update, context):
    logger.info(f"Got message: {to_json_string(update)}")
    chat = update.message.chat
    if chat.type != Chat.GROUP and chat.type != Chat.SUPERGROUP:
        return None

    text = update.message.text
    if text is None:
        return

    try:
        text = update.message.text
        if text.endswith(f'@{bot_name}'):
            text = text[:-11]
        if text == '/current' or text == '/balance':
            graph(tmp_path)
            update.message.reply_photo(photo=open(tmp_path, 'rb'), caption=balance_text())
            return
        if text == '/all':
            with sqlite3.connect(DBFILE) as con:
                rows = con.execute(f'select * from spendings;').fetchall()
            message = '\n'.join(['  '.join(map(str, r)) for r in rows])
            msgs = [message[i:i + 4096] for i in range(0, len(message), 4096)]
            for text in msgs:
                reply(update, text)
            return
        if text[0].isalpha():
            return
        try:
            m = re.search('^(\d+)\s(.*)', text)
            val = int(m.group(1))
            descr = m.group(2)
        except Exception as e:
            reply(update, 'Не могу распознать. Ожидается текст в формате "<число> описание"')
            return

        con = sqlite3.connect(DBFILE)
        with con:
            res = con.execute(f'INSERT INTO spendings(ts, val, descr, user) VALUES (:ts, :val, :descr, :user)',
                              {'ts': datetime.now(), 'val': val, 'descr': descr,
                               'user': update.message.from_user.username})

        keyboard = [[
            InlineKeyboardButton('разделить поровну', callback_data=f'split {res.lastrowid}'),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(balance_text(), reply_markup=reply_markup)
        return

    except Exception as e:
        logger.exception('Cannot handle request')
        reply(update, f'Произошла какая-то ошибка: {e}')


def graph(path):
    days_from_start_of_month = datetime.now().day
    results = {}
    con = sqlite3.connect(DBFILE)
    for day in range(1, days_from_start_of_month + 1):
        q = f"select sum(val) from spendings where ts >= '2023-11-{day:02}' and ts < '2023-11-{day + 1:02}';"
        res = con.execute(q).fetchone()[0] or 0
        results[str(day)] = res
    con.close()

    plt.bar(results.keys(), results.values())
    plt.grid()
    plt.savefig(path)
    plt.close()


def migration():
    con = sqlite3.connect(DBFILE)
    con.execute(
        "CREATE TABLE IF NOT EXISTS spendings(id INTEGER PRIMARY KEY, ts timestamp, val integer, descr VARCHAR, user VARCHAR)")
    with con:
        v, = con.execute("PRAGMA user_version").fetchone()
    if v == 0:
        with con:
            con.execute('ALTER TABLE spendings ADD COLUMN user VARCHAR;')
            con.execute('PRAGMA user_version = 1;')
    elif v == 1:
        pass
    else:
        raise RuntimeError(
            f"Database is at version {v}. This version of software only supports opening versions 0 or 1.")


def main():
    migration()
    updater = Updater(os.environ['BOT_TOKEN'], use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(MessageHandler(Filters.all, handle_message))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
