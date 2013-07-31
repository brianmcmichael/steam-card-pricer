import re, math, os
import datetime, time
import urllib.request, html
import sqlite3

################################################################################
# pulls the card prices from the Steam market
def updateData(specific=""):
  failureThreshold = 35
  failures = 0

  if specific == '':
    print('updating data')
  con = sqlite3.connect('data.sqlite')
  cur = con.cursor()

  i = 0
  pages = 1
  while i < pages:
    failed = False
    if specific == '':
      print('page %d:' % (i + 1)) 

    # get the page - why 95 instead of 100? the results sometimes shift
    # every so slightly during their download
    url = 'http://steamcommunity.com/market/search/render/?query=trading'
    url += '%%20card%%20%s&start=%d&count=100' % (specific, (i * 95))
    contents = ''
    try:
      with urllib.request.urlopen(url, timeout=10) as s:
        contents = s.read()

    # timeout or error reaching site
    except:
      failed = True

    # decode contents
    if not failed:
      contents = contents.decode('unicode-escape')
      contents = contents.replace('\\/','/')

      # internal API failure or market down
      if "There was an error performing your search." in contents:
        failed = True

    # retry page if failed
    if failed:
      print('  page failed, waiting 5 seconds to retry...')
      failures += 1
      time.sleep(5)
      if failures == failureThreshold:
        print('too many failures, exiting...')
        exit()
      continue

    if specific == '':
      print('  parsing')

    # get page count if first page
    if (i == 0 and specific == ""):
      pages = re.findall('"total_count":(\d+)', contents)[0]
      pages = int(math.ceil(float(pages) / 95))
      print('there are %d pages' % pages)

    # regex data out
    names = re.findall('market_listing_item_name".*?>(.*?)<', contents)
    games = re.findall('market_listing_game_name">(.*?)<', contents)
    urls = re.findall('/listings/(\d+/.*?)">', contents)
    prices = re.findall('&#36;(\d+.\d+)', contents)
    counts = re.findall('market_listing_num_listings_qty">(.*?)<', contents)

    # handle each match
    for j in range(len(names)):
      name = names[j]
      game = games[j]

      # skip emoticons etc
      if 'Trading Card' not in game:
        continue

      url = urls[j].replace('?filter=trading%20card','')

      # add the game to DB if new
      q = "INSERT OR IGNORE INTO games VALUES("
      q += "'%s'" % game
      q += ", 0"
      q += ")"
      cur.execute(q)

      # replace the card listing in DB with newest price
      q = "INSERT OR REPLACE INTO cards VALUES("
      q += "'%s'" % game
      q += ", '%s'" % name
      q += ", '%s'" % url
      q += ", %.2f" % float(prices[j])
      q += ", '%s'" % str(datetime.datetime.utcnow())
      q += ", %d" % int(counts[j].replace(',', ''))
      q += ")"
      try:
        cur.execute(q)
      except:
        print("  failed on query:")
        print(q)
        exit()
    i += 1

  # save changes
  con.commit()
  con.close()

def getClasses(name, short):
  classes = ''
  if 'Foil Trading Card' in name:
    classes += ' foil'
  if short:
    classes += ' bad'
  return classes

################################################################################
# escapes a string for HTML output
def escape(s):
  s = html.escape(s)
  s = s.encode('ascii', 'xmlcharrefreplace')
  s = s.decode('ascii')
  return s

################################################################################
# generates the HTML
def updateSite():
  print('updating the site')
  o = open("template.html").read()

  con = sqlite3.connect('data.sqlite')
  cur = con.cursor()

  # running totals for all sets
  totalStandard = 0
  totalFoil = 0

  # insert most expensive card stats
  q = 'select * from cards order by cost desc limit 1'
  cur.execute(q)
  a = cur.fetchone()
  o = o.replace('[EXPENSIVE-NAME]', escape(a[1]))
  listingsBase = 'http://steamcommunity.com/market/listings/'
  o = o.replace('[EXPENSIVE-URL]', (listingsBase + a[2]))
  o = o.replace('[EXPENSIVE-PRICE]', '$%.2f' % a[3])


  # build the table, get price of all sets
  table = '<table class="sortable">\n<tr><th>Game</th><th># Cards</th>'
  table += '<th>Set Price</th><th>Avg. Card Price</th>'
  table += '<th class="discount">"Discount"</th>'
  table += '<th class="listings">Listings</th></tr>\n'

  # query the card data
  q = "select"
  q += " g.name"
  q += ", case when g.count = count(c.name) then sum(c.cost)"
  q += " else sum(c.cost) * g.count / count(c.name) end as 'costforall'"
  q += ", g.count"
  q += ", count(c.name)"
  q += ", sum(c.count)"
  q += " from games g"
  q += " inner join cards c on c.game = g.name"
  q += " group by g.name"
  q += " order by costforall asc;"
  cur.execute(q)
  a = cur.fetchall()

  searchBase = 'http://steamcommunity.com/market/search?q='

  # add row for each set
  for b in a:
    # print game name and link
    game = b[0]

    gameEnc = escape(game)
    gameEnc = gameEnc.replace('Foil Trading Card', '(Foil)')
    gameEnc = gameEnc.replace('Trading Card', '')

    gameSearchEnc = game.replace('&', '%26')
    gameSearchEnc = escape(gameSearchEnc)
    search = searchBase + '%22' + gameSearchEnc + '%22'

    table += '<tr class="%s">' % getClasses(game, (b[3] < b[2]))
    table += '<td>%s' % gameEnc
    table += ' <a target="_blank" href="%s">&rarr;</a></td>' % search

    # add game price to totals
    if 'Foil Trading Card' in game:
      totalFoil += b[1]
    else:
      totalStandard += b[1]

    # print card count, set price, and average card price
    table += '<td>%d</td>' % b[2]
    table += '<td>$%0.2f</td>' % b[1]
    avg = (b[1] / b[2])
    table += '<td>$%0.2f</td>' % avg

    # print discount
    discount = '&nbsp;'
    if 'Foil Trading Card' not in game and ('Steam Summer Getaway' not in game):
      discount = '$%0.2f' % (avg * 0.85 * math.ceil(float(b[2]) / 2))
    table += '<td class="discount">%s</td>' % discount
    
    # print listings
    listings = '&nbsp;'
    if b[4] != None and b[4] > b[2]:
      listings = '{:,}'.format(b[4])
    table += '<td class="listings">%s</td>' % listings
    table += '</tr>\n'
    
  table += '</tbody></table>'

  o = o.replace('[TABLE]', table)

  # swap stats into HTML
  t = time.strftime('%Y-%m-%d %H:%M', time.gmtime()) + " GMT"
  o = o.replace('[TIME]', t)

  # get total games
  q = "SELECT count(*) FROM games where name not like '%Foil Trading Card%'"
  cur.execute(q)
  a = cur.fetchone()
  o = o.replace('[GAME-COUNT]', str(a[0]))

  # get totals
  o = o.replace('[TOTAL-S]', "${:,.2f}".format(totalStandard))
  o = o.replace('[TOTAL-F]', "~${:,.2f}".format(totalFoil))
  o = o.replace('[TOTAL]', "~${:,.2f}".format(totalFoil + totalStandard * 5))

  # get median prices
  q = "SELECT"
  q += " cost"
  q += " FROM (select * from cards"
  q += " where game not like '%Foil Trading Card%') as nf"
  q += " ORDER BY cost"
  q += " LIMIT 1"
  q += " OFFSET (SELECT COUNT(*) FROM ("
  q += "select * from cards where game not like '%Foil Trading Card%') as nf" 
  q += ") / 2"
  cur.execute(q)
  a = cur.fetchone()
  o = o.replace('[MEDIAN-STANDARD-PRICE]', "${:,.2f}".format(a[0]))

  q = "SELECT cost FROM (select * from cards where game like '%Foil Trading Card%') as nf ORDER BY cost LIMIT 1 OFFSET (SELECT COUNT(*) FROM (select * from cards where game like '%Foil Trading Card%') as nf ) / 2"
  cur.execute(q)
  a = cur.fetchone()
  o = o.replace('[MEDIAN-FOIL-PRICE]', "${:,.2f}".format(a[0]))
  

  # finish up
  con.close()
  f = open('index.html', 'w')
  f.write(o)
  f.close()

################################################################################
# updates the total card counts as info is available
def updateCounts():
  print('updating set counts')

  con = sqlite3.connect('data.sqlite')
  cur = con.cursor()

  # selects specified number of cards for a game and also the current count
  # of cards
  q = "select g.name, g.count, count(c.url) from games g inner join cards c on c.game = g.name where g.name not like '%Foil Trading Card%' group by g.name"
  cur.execute(q)
  a = cur.fetchall()
  for b in a:
    game = b[0]
    target = b[1]
    counted = b[2]

    q = "update games set count = %d where name = '%s'" % (counted, game)
    cur.execute(q)
    target = counted

    # copy standard set counts to foil sets
    game = game.replace('Trading Card', 'Foil Trading Card')
    q = "insert or replace into games values('%s', %d)" % (game, target)
    cur.execute(q)

  con.commit()
  con.close()

################################################################################
# commits via git
def upload():
  print('uploading')

  os.system('git commit -a -m "automatic update"')
  os.system('git push')

################################################################################
# Program entrypoint.
if __name__ == "__main__":
  updateData()
  updateCounts()
  updateSite()
  upload()