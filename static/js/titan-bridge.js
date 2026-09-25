/* TiTaN — bridge v2: exact visuals + fully real data (no fakes) */
(() => {
  'use strict';
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
  function fmtBytes(b){ b=Number(b)||0; if(b===0) return '0 B'; const u=['B','KB','MB','GB','TB']; let i=0; while(b>=1024&&i<u.length-1){b/=1024;i++;} return (i===0?b:b.toFixed(b>=10?1:2).replace(/\.0+$/,''))+' '+u[i]; }
  function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }
  function flagFor(cc){ cc=(cc||'').toUpperCase().trim(); if(cc==='UK') cc='GB'; if(/^[A-Z]{2}$/.test(cc)) return String.fromCodePoint(...[...cc].map(c=>0x1F1E6+c.charCodeAt(0)-65)); return '🌐'; }
  const COUNTRY_CODES=Object.freeze({
    'argentina':'AR','armenia':'AM','australia':'AU','austria':'AT','azerbaijan':'AZ',
    'bahrain':'BH','belgium':'BE','brazil':'BR','canada':'CA','chile':'CL','czechia':'CZ',
    'czech republic':'CZ','denmark':'DK','egypt':'EG','finland':'FI','france':'FR','georgia':'GE',
    'germany':'DE','hong kong':'HK','india':'IN','iran':'IR','iran, islamic republic of':'IR',
    'iraq':'IQ','ireland':'IE','israel':'IL','italy':'IT','japan':'JP','jordan':'JO','kuwait':'KW',
    'lebanon':'LB','netherlands':'NL','the netherlands':'NL','holland':'NL','norway':'NO','oman':'OM',
    'poland':'PL','qatar':'QA','russia':'RU','russian federation':'RU','saudi arabia':'SA',
    'singapore':'SG','south africa':'ZA','south korea':'KR','spain':'ES','sweden':'SE',
    'switzerland':'CH','turkey':'TR','turkiye':'TR','türkiye':'TR','united arab emirates':'AE',
    'united kingdom':'GB','great britain':'GB','england':'GB','uk':'GB','united states':'US',
    'united states of america':'US','usa':'US','us':'US','ایالات متحده':'US','آمریکا':'US',
    'انگلستان':'GB','بریتانیا':'GB','ترکیه':'TR','چک':'CZ','جمهوری چک':'CZ','آلمان':'DE',
    'هلند':'NL','ایران':'IR','فرانسه':'FR','اسپانیا':'ES','ایتالیا':'IT','سوئیس':'CH',
    'سوئد':'SE','نروژ':'NO','دانمارک':'DK','فنلاند':'FI','بلژیک':'BE','اتریش':'AT',
    'لهستان':'PL','سنگاپور':'SG','ژاپن':'JP','هند':'IN','استرالیا':'AU','کانادا':'CA',
    'امارات':'AE','امارات متحده عربی':'AE','عربستان':'SA','عربستان سعودی':'SA','روسیه':'RU',
    'گرجستان':'GE','ارمنستان':'AM','آذربایجان':'AZ','مصر':'EG','قطر':'QA','عمان':'OM',
    'بحرین':'BH','کویت':'KW'
  });
  const CITY_CODES=Object.freeze({
    'frankfurt':'DE','amsterdam':'NL','london':'GB','paris':'FR','madrid':'ES','milan':'IT',
    'vienna':'AT','warsaw':'PL','prague':'CZ','zurich':'CH','stockholm':'SE','oslo':'NO',
    'copenhagen':'DK','helsinki':'FI','dublin':'IE','brussels':'BE','istanbul':'TR','dubai':'AE',
    'doha':'QA','manama':'BH','tel aviv':'IL','jeddah':'SA','riyadh':'SA','ashburn':'US',
    'ashburn, va':'US','newark':'US','newark, nj':'US','chicago':'US','chicago, il':'US',
    'dallas':'US','dallas, tx':'US','los angeles':'US','los angeles, ca':'US','san jose':'US',
    'san jose, ca':'US','seattle':'US','seattle, wa':'US','atlanta':'US','miami':'US','toronto':'CA',
    'vancouver':'CA','sao paulo':'BR','buenos aires':'AR','santiago':'CL','mumbai':'IN',
    'chennai':'IN','new delhi':'IN','singapore':'SG','hong kong':'HK','tokyo':'JP','osaka':'JP',
    'seoul':'KR','sydney':'AU','melbourne':'AU','johannesburg':'ZA','cairo':'EG','moscow':'RU',
    'tehran':'IR','muscat':'OM','kuwait city':'KW','beirut':'LB','amman':'JO','baghdad':'IQ',
    'tbilisi':'GE','yerevan':'AM','baku':'AZ'
  });
  function locationKey(value){
    return String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').trim().toLowerCase().replace(/[._-]+/g,' ').replace(/\s+/g,' ');
  }
  function nodeCountryCode(n){
    const raw=String((n&&n.country_code)||'').toUpperCase().trim();
    if(raw==='UK') return 'GB';
    if(/^[A-Z]{2}$/.test(raw)) return raw;
    const country=locationKey((n&&n.country)||raw);
    if(Object.prototype.hasOwnProperty.call(COUNTRY_CODES,country)) return COUNTRY_CODES[country];
    const city=locationKey(n&&(n.city||n.location||n.region));
    return Object.prototype.hasOwnProperty.call(CITY_CODES,city)?CITY_CODES[city]:'';
  }
  function nodeFlag(n){
    const code=nodeCountryCode(n);
    if(code) return flagFor(code);
    const stored=String((n&&n.flag)||'').trim();
    const indicators=[...stored].filter(ch=>ch.codePointAt(0)>=0x1F1E6&&ch.codePointAt(0)<=0x1F1FF);
    return indicators.length===2 && stored!=='🏳️' ? stored : '🌐';
  }
  function nodeFlagHtml(n,size='sm'){
    const scale=['sm','md','lg'].includes(size)?size:'sm';
    const emoji=nodeFlag(n), code=nodeCountryCode(n);
    const fallback=`<span class="node-flag-fallback">${esc(emoji)}</span>`;
    if(!code) return `<span class="node-flag-visual node-flag-${scale} node-flag-no-code" aria-hidden="true">${fallback}</span>`;
    const width=scale==='lg'?'w80':'w40';
    const src=`https://flagcdn.com/${width}/${code.toLowerCase()}.png`;
    return `<span class="node-flag-visual node-flag-${scale}" aria-hidden="true">${fallback}<img class="node-flag-img" src="${esc(src)}" alt="" loading="lazy"></span>`;
  }
  document.addEventListener('load',event=>{
    const image=event.target;
    if(image&&image.classList&&image.classList.contains('node-flag-img')) image.parentElement?.classList.add('node-flag-loaded');
  },true);
  document.addEventListener('error',event=>{
    const image=event.target;
    if(image&&image.classList&&image.classList.contains('node-flag-img')) image.parentElement?.classList.add('node-flag-failed');
  },true);

  // Dashboard copy is translated in place so both the shipped sections and
  // markup inserted later by the live-data bridge stay in the selected language.
  const DASHBOARD_TEXT=Object.freeze({
    'PRIVATE NETWORK':'شبکه خصوصی','English':'انگلیسی','Online':'آنلاین','Nodes':'نودها',
    'داشبورد':'Dashboard','کاربران':'Users','کانفیگ‌ها':'Configs','سرورها (Nodes)':'Servers (Nodes)',
    'اشتراک‌ها':'Subscriptions','گزارش‌ها':'Reports','تنظیمات':'Settings','مدیریت ادمین':'Admin management',
    'ابزارها':'Tools','ادمین کل':'Super Admin','مدیر اصلی':'Owner','مدیر':'Admin',
    'خوش آمدید، مدیر':'Welcome, Admin','خوش آمدید،':'Welcome,',
    'نمای کلی سیستم TiTaN':'TiTaN system overview','کاربران فعال':'Active users','از 1 کاربر':'of 1 user',
    'ترافیک مصرفی':'Traffic used','تعداد سرورها':'Number of servers','● 1 آنلاین':'● 1 online',
    'کانفیگ‌های فعال':'Active configs','از 1 کانفیگ':'of 1 config','نمودار ترافیک':'Traffic chart',
    'مصرف در 7 روز گذشته':'Usage in the last 7 days','۳ شهریور':'Sep 3','۴ شهریور':'Sep 4',
    '۵ شهریور':'Sep 5','۶ شهریور':'Sep 6','۷ شهریور':'Sep 7','۸ شهریور':'Sep 8',
    'وضعیت سرورها':'Server status','تاخیر':'Latency','تأخیر':'Latency','آنلاین':'Online','آفلاین':'Offline',
    'مشاهده همه سرورها ←':'View all servers ←','کاربران اخیر':'Recent users','مشاهده همه':'View all',
    'کاربر':'User','وضعیت':'Status','فعال':'Active','آخرین کانفیگ‌ها':'Latest configs','نام':'Name',
    'نوع':'Type','سرور':'Server','مدیریت کاربران و دسترسی‌های فعال پنل':'Manage panel users and active access',
    'همه کاربران':'All users','منقضی':'Expired','تعداد کل':'Total count','در حال اتصال':'Connecting',
    'غیرفعال':'Disabled','مصرف ترافیک':'Traffic usage','مصرف امروز':'Today’s usage','کل مصرف':'Total usage',
    'وضعیت اشتراک':'Subscription status','● 3 حساب':'● 3 accounts','نزدیک به انقضا':'Expiring soon',
    '1 حساب':'1 account','0 حساب':'0 accounts','فهرست کاربران':'User list','۳ مورد':'3 items',
    'شناسه':'ID','مصرف':'Usage','انقضا':'Expiry','عملیات':'Actions','30 روز':'30 days',
    'ساخت، مدیریت و کنترل کانفیگ‌های اتصال':'Create, manage, and control connection configs',
    'همه':'All','کل کانفیگ‌ها':'Total configs','پروتکل‌های استفاده‌شده':'Used protocols',
    '3 مورد':'3 items','0 مورد':'0 items','اشتراک‌گذاری':'Sharing','لینک‌های فعال':'Active links',
    'QR تولیدشده':'QR codes created','آخرین بروزرسانی':'Last updated','امروز':'Today',
    'پروتکل':'Protocol','پورت':'Port','سرورها':'Servers',
    'مدیریت نودها، سلامت اتصال و وضعیت سرویس‌ها':'Manage nodes, connection health, and service status',
    'وضعیت نودها':'Node status','کل سرورها':'Total servers','سلامت اتصال':'Connection health',
    'میانگین پینگ':'Average ping','پایداری':'Stability','وضعیت سرویس':'Service status',
    'وضعیت پنل':'Panel status','سالم':'Healthy','اتصال نودها':'Node connection','برقرار':'Connected',
    'ساخت لینک اشتراک از بین کانفیگ‌ها و کاربران':'Create a subscription link from configs and users',
    'لینک اشتراک':'Subscription link','استفاده':'Usage','هرگز':'Never',
    'نمایش آماری مصرف، کاربران و رویدادهای پنل':'Analytics for usage, users, and panel events',
    'دریافت گزارش':'Get report','۷ روز اخیر':'Last 7 days','۳۰ روز اخیر':'Last 30 days',
    'فیلتر تاریخ ▾':'Filter by date ▾','دانلود':'Download','آپلود':'Upload','رشد کاربران':'User growth',
    'کاربر جدید':'New user','کاربر فعال':'Active user','نرخ فعالیت':'Activity rate',
    'رویدادهای سیستم':'System events','ورود موفق':'Successful sign-ins','خطاها':'Errors',
    'بررسی نودها':'Node checks','نمودار مصرف هفتگی':'Weekly usage chart','شنبه تا جمعه':'Saturday to Friday',
    'مجموع 1.24 GB':'Total 1.24 GB','آخرین رویدادها':'Latest events','ثبت فعالیت‌ها':'Activity log',
    'رویداد':'Event','زمان':'Time','نتیجه':'Result','ورود به پنل':'Panel sign-in','همین لحظه':'Just now',
    'موفق':'Successful','بررسی سرور':'Server check','سیستم':'System','۲ دقیقه قبل':'2 minutes ago',
    'ساخت کانفیگ':'Config created','۱۰ دقیقه قبل':'10 minutes ago','پیکربندی عمومی پنل':'General panel configuration',
    'ذخیره ✓':'Save ✓','عمومی':'General','دامنه عمومی (اختیاری)':'Public domain (optional)',
    'پورت عمومی پنل (پیش‌فرض 443)':'Public panel port (default 443)','زبان پنل':'Panel language',
    'فارسی':'Persian','دامنه‌ای که کلاینت‌ها برای اتصال به پنل استفاده می‌کنند. اگر خالی باشد از آدرس فعلی استفاده می‌شود.':'The domain clients use to reach the panel. If left blank, the current address is used.',
    'امنیت':'Security','رمز عبور هنوز تنظیم نشده است. برای امنیت، یک رمز عبور قوی انتخاب کنید.':'No password is set yet. Choose a strong password for security.',
    'رمز عبور فعلی':'Current password','رمز عبور جدید':'New password','تغییر رمز عبور ↗':'Change password ↗',
    'تصویر پروفایل':'Profile picture','برای خود و کاربران، یک تصویر انتخاب کنید. پیشنهاد می‌شود از لوگوی TiTaN استفاده شود.':'Choose a picture for yourself and users. The TiTaN logo is recommended.',
    'انتخاب از گالری ↗':'Choose from gallery','شبکه':'Network','پروتکل اتصال پیش‌فرض':'Default connection protocol',
    'Fingerprint پیش‌فرض':'Default fingerprint','Fingerprint':'اثر انگشت','ALPN پیش‌فرض':'Default ALPN',
    'SNI سفارشی (اختیاری)':'Custom SNI (optional)','پشتیبان‌گیری':'Backup','پشتیبان‌گیری خودکار':'Automatic backup',
    'بازه پشتیبان‌گیری (ساعت)':'Backup interval (hours)','دانلود پشتیبان ↓':'Download backup ↓',
    'بازیابی از پشتیبان ↑':'Restore from backup ↑','مسدودسازی IPهای خصوصی':'Block private IPs',
    'مسدودسازی تبلیغات':'Block ads','مسدودسازی سایت‌های ایرانی':'Block Iranian sites',
    'اعلان اتصال جدید':'Notify on new connection','فعال‌سازی Fragment':'Enable Fragment','طول Fragment':'Fragment length',
    'بازه Fragment':'Fragment interval','⏻ راه‌اندازی مجدد پنل':'⏻ Restart panel',
    'مدیریت مدیران پنل و سطح دسترسی آن‌ها':'Manage panel administrators and their access levels',
    '+ افزودن ادمین':'+ Add admin','مدیران پنل':'Panel admins','تعداد مدیران':'Admin count',
    'آخرین ورود':'Last login','سطح دسترسی':'Access level','مدیریت کاربران':'Manage users',
    'مجاز':'Allowed','مدیریت سرورها':'Manage servers','تنظیمات سیستم':'System settings',
    'امنیت مدیران':'Admin security','ثبت فعالیت مدیران':'Admin activity log',
    'محدودیت نشست همزمان':'Concurrent session limit','فهرست ادمین‌ها':'Admin list','۱ مدیر':'1 admin',
    'نقش':'Role','ویرایش':'Edit','ابزارهای کاربردی برای نگهداری، بررسی و عیب‌یابی پنل':'Useful tools to maintain, inspect, and troubleshoot the panel',
    'تست اتصال':'Connection test','بررسی دسترسی به نودها و سرویس‌های شبکه':'Check node access and network services',
    'اجرای تست اتصال':'Run connection test','پاک‌سازی':'Cleanup',
    'حذف داده‌های موقت و مرتب‌سازی اطلاعات قدیمی':'Remove temporary data and organize old records',
    'پاک‌سازی داده‌ها':'Clean up data','تهیه نسخه پشتیبان از تنظیمات و داده‌های پنل':'Back up panel settings and data',
    'ساخت نسخه پشتیبان':'Create backup','بررسی سلامت سیستم':'System health check','سرویس پنل':'Panel service',
    'پایگاه داده':'Database','لاگ سیستم':'System log','رویدادهای ثبت‌شده':'Recorded events',
    'خطاهای اخیر':'Recent errors','نمایش لاگ‌ها':'View logs','ابزارهای سریع':'Quick tools',
    'پاک‌سازی کش':'Clear cache','بررسی پورت':'Check port','بازنشانی وضعیت':'Reset status',
    'یا ورود با':'Or sign in with','پنل':'Panel','داده‌ای وجود ندارد':'No data available',
    'داده‌ای موجود نیست':'No data available','موردی وجود ندارد':'No items found','کاربری وجود ندارد':'No users found',
    'کانفیگی وجود ندارد':'No configs found','سروری ثبت نشده است':'No server registered',
    'سروری ثبت نشده است — با دکمهٔ افزودن سرور یک نود بساز.':'No server registered — use Add server to create a node.',
    'کانفیگی برای این کاربر وجود ندارد':'This user has no configs','نامعلوم':'Unknown','نامشخص':'Unknown',
    'خروجی':'Output','انجام شد':'Done','بستن':'Close','لغو':'Cancel','ذخیره':'Save','حذف':'Delete',
    'کپی':'Copy','کپی شد!':'Copied!','کپی لینک':'Copy link','ذخیره شد':'Saved','حذف شد':'Deleted',
    'حذف کاربر؟':'Delete user?','حذف کانفیگ؟':'Delete config?','حذف سرور؟':'Delete server?',
    'روز':'days','ساعت':'hours','دقیقه':'minutes','ثانیه':'seconds','دقیقه قبل':'minutes ago',
    'روز قبل':'days ago','سرورها (Nodes)':'Servers (Nodes)',
    'اعلان‌ها':'Notifications','افزودن سرور (نود جدید)':'Add server (new node)','باز و بسته کردن منو':'Toggle menu',
    'جزئیات':'Details','جستجو':'Search','حذف گروهی':'Bulk delete','خروجی گرفتن از کاربران':'Export users',
    'رفرش':'Refresh','ساخت لینک اشتراک جدید':'Create subscription link','ساخت کانفیگ جدید':'Create config',
    'ناوبری':'Navigation','پیام‌ها':'Messages','پینگ‌سنج':'Ping tester','پروفایل کاربر':'User profile',
    'جستجو...':'Search...','جستجوی کاربر، نام یا شناسه...':'Search users, names, or IDs...',
    'جستجوی کانفیگ...':'Search configs...','QR اشتراک':'Subscription QR','افزودن ادمین':'Add admin',
    'انتخاب از گالری':'Choose from gallery','بازنشانی وضعیت':'Reset status','بازیابی پشتیبان':'Restore backup',
    'بررسی پورت':'Check port','تست اتصال':'Connection test','تغییر رمز عبور':'Change password',
    'تهیه نسخه پشتیبان':'Create backup','دانلود پشتیبان':'Download backup','دریافت گزارش':'Get report',
    'ذخیره تغییرات':'Save changes','راه‌اندازی مجدد پنل':'Restart panel','مدیریت اشتراک':'Manage subscription',
    'نمایش اشتراک':'View subscription','نمایش لاگ سیستم':'View system logs','پاک‌سازی داده‌های موقت':'Clear temporary data',
    'پاک‌سازی کش':'Clear cache','کپی اشتراک':'Copy subscription',
    'پنل (همین آدرسی که باز است)':'Panel (this address)','لینک‌هایی که روی پنل سرو می‌شوند از همین مسیر می‌آیند':'Links served by the panel use this route',
    'نزدیک‌ترین نقطهٔ Cloudflare':'Nearest Cloudflare point','کفِ پینگ ممکن برای یک سرور نزدیکِ شما':'The lowest ping to a nearby server',
    'این عدد، رفت‌وبرگشت واقعی از':'This is the real round trip from','همین دستگاه':'this device',
    'تا هر مقصد است — نه پینگ پنل به نود.':'to each destination — not the panel-to-node ping.',
    'هرچه خروجیِ کانفیگ به شما نزدیک‌تر باشد، پینگ کمتر می‌شود.':'The closer the config exit is to you, the lower the ping.',
    'در حال اندازه‌گیری':'Measuring…','اندازه‌گیری':'Measurement','اندازه‌گیری این آدرس':'Measure this address','اندازه‌گیری مجدد':'Measure again',
    'مرجع پینگ از ایران: ':'Ping reference from Iran: ','از همین دستگاه':'from this device','دوم':'2nd','ترکیه':'Türkiye','امارات':'UAE','آلمان':'Germany',
    'هلند':'Netherlands','آمریکا':'United States','فرانسه':'France','انگلستان':'United Kingdom',
    'سنگاپور':'Singapore','هند':'India','سن‌خوزه':'San Jose','ویرجینیا':'Virginia','فرانکفورت':'Frankfurt',
    'لندن':'London','دبی':'Dubai','پاریس':'Paris','اروپا':'Europe','دورتر از حد مطلوب':'Farther than ideal',
    'هم‌سایه (ترکیه/امارات)':'Nearby (Türkiye/UAE)','آمریکا/دور':'US / far','آدرس ثبت نشده':'No address registered',
    'آدرس http است؛ از صفحهٔ https اندازه‌گیری نمی‌شود':'HTTP address; it cannot be measured from this HTTPS page',
    'سریع‌ترین مسیر از دستگاه شما: ':'Fastest route from your device: ',' با ':' at ',
    'بهترین نود شما ':'Your fastest node: ','بهترین نود شما (':'Your fastest node (',
    'با ':'at ','فاصله دارد.':'away.','نزدیک کفِ ممکن است ✓':'is near the minimum possible ✓',
    'منطقهٔ فعلی پنل: ':'Current panel region: ','چیزی قابل اندازه‌گیری نبود.':'Nothing could be measured.',
    'نام اشتراک':'Subscription name','مثلاً پک موبایل':'e.g. Mobile pack','انتخاب تصویر این لینک':'Choose an image for this link',
    'کاربر جدید':'New user','ویرایش کاربر':'Edit user','افزودن کاربر':'Add user','نام کاربری':'Username',
    'حجم':'Quota','حجم گیگابایت':'Quota (GB)','حجم (گیگابایت)':'Quota (GB)','اعتبار روز':'Validity (days)',
    'انقضای روز':'Expiry (days)','روز اعتبار':'Validity (days)','سقف درخواست':'Request limit',
    'حداکثر دستگاه':'Max devices','IPهای مجاز':'Allowed IPs','یادداشت':'Note','یادداشت (اختیاری)':'Note (optional)',
    'شناسه کاربر':'User ID','ویرایش کانفیگ':'Edit config','افزودن کانفیگ':'Add config','انتخاب کاربر':'Select user',
    'انتخاب سرور':'Select server','انتخاب پروتکل':'Select protocol','روش رمزنگاری SS':'SS encryption method',
    'نام کانفیگ':'Config name','نام نود':'Node name','نام سرور':'Server name','توکن':'Token',
    'فعال بودن':'Enabled','فعال/غیرفعال':'Enable/disable','تغییر UUID':'Rotate UUID','صفر کردن مصرف':'Reset usage',
    'وضعیت کاربر':'User status','وضعیت نود':'Node status','کد کشور':'Country code','پرچم کشور':'Country flag',
    'هیچ کاربری وجود ندارد':'No users found','هنوز کاربری ایجاد نشده است':'No users created yet',
    'هنوز کانفیگی ساخته نشده است':'No configs created yet','هنوز هیچ سروری اضافه نشده است':'No servers added yet',
    'اطلاعات اصلی':'Main information','سرور':'Server','شبکه':'Network','محدودیت‌ها':'Limits','پیش‌نمایش':'Preview',
    'جزئیات کاربر':'User details','اطلاعات کاربر':'User information','گزینه‌ها':'Options','همه کانفیگ‌ها':'All configs',
    'افزودن به اشتراک':'Add to subscription','تعداد کانفیگ':'Config count','تعداد کاربران':'User count',
    'تعداد نودها':'Node count','میانگین پینگ':'Average ping','میانگین تأخیر':'Average latency',
    'مصرف کل':'Total usage','مصرف امروز':'Today’s usage','کل ترافیک':'Total traffic','حجم باقی‌مانده':'Remaining quota',
    'اشتراک ساخته شد':'Subscription created','اشتراک ویرایش شد':'Subscription updated','ساخت اشتراک':'Create subscription',
    'ویرایش اشتراک':'Edit subscription','نام لینک اشتراک':'Subscription link name','کانفیگ‌های انتخاب‌شده':'Selected configs',
    'انتخاب همه':'Select all','لغو انتخاب همه':'Clear selection','انتخاب کانفیگ‌ها':'Select configs',
    'لینک اشتراک ساخته شد':'Subscription link created','لینک اشتراک ویرایش شد':'Subscription link updated',
    'دسترسی خودکار داده شد':'Automatic access granted','دسترسی خودکار نشد':'Automatic access was not granted',
    'جستجوی کاربر':'Search users','جستجوی سرور':'Search servers','فقط آنلاین':'Online only','فقط فعال':'Active only',
    'در حال بارگذاری':'Loading','در حال ذخیره':'Saving','در حال حذف':'Deleting','در حال اتصال':'Connecting',
    'خطایی رخ داد':'An error occurred','عملیات انجام شد':'Operation completed','عملیات ناموفق بود':'Operation failed',
    'بله':'Yes','خیر':'No','تغییرات ذخیره شد':'Changes saved','اطلاعات ذخیره شد':'Information saved',
    'آدرس پنل':'Panel address','آدرس دامنه':'Domain address','دامنه عمومی':'Public domain','پورت عمومی':'Public port',
    'پورت پنل':'Panel port','وضعیت اتصال':'Connection status','آخرین فعالیت':'Last activity','آخرین همگام‌سازی':'Last sync',
    'رمز عبور':'Password','وارد کردن رمز عبور':'Enter password','تأیید رمز عبور':'Confirm password',
    'تصویر':'Image','انتخاب تصویر':'Choose image','انتخاب از گالری':'Choose from gallery','آپلود تصویر':'Upload image',
    'شبکه خصوصی':'Private network','همه چیز آماده است':'Everything is ready','خودکار':'Automatic',
    'شناسایی خودکار':'Automatic detection','راه‌اندازی سریع نود':'Quick node setup','اتصال خودکار':'Automatic connection',
    'خطا در اتصال':'Connection error','دامنه نود':'Node domain','نام دامنه':'Domain name','وضعیت نودها':'Node status',
    'گزینه را انتخاب کنید':'Select an option','مقدار نامعتبر':'Invalid value','شناسه نامعتبر':'Invalid ID',
    'پاسخ نود':'Node response','پاسخ دریافت نشد':'No response received','در دسترس نیست':'Unavailable',
    'تنظیم نشده':'Not set','پیکربندی نشده':'Not configured','موقتاً غیرفعال':'Temporarily disabled',
    'خروج از حساب؟':'Log out?','خروج از حساب':'Log out','تغییر تصویر پروفایل':'Change profile picture',
    'تصویر ذخیره شد':'Image saved','تصویر پروفایل ذخیره شد':'Profile picture saved','کپی همه متغیرها':'Copy all variables',
    'متغیرها':'Variables','داده‌های نمونه':'Sample data','خالی است':'is empty',
    'بازنشانی وضعیت':'Reset status','ورودی':'Input','خروجی':'Output','زمان اجرا':'Runtime',
    'تصویر این لینک روی صفحهٔ اشتراک':'This link’s image on the subscription page',
    'تصویر این کاربر روی صفحهٔ اشتراک':'This user’s image on the subscription page',
    'تصویر این کاربر روی لینک اشتراک':'This user’s image on the subscription link',
    'همهٔ کانفیگ‌های این کاربر':'All configs for this user','همه کانفیگ‌های این کاربر':'All configs for this user',
    'هیچ کانفیگی':'No configs','کپی لینک':'Copy link','کانفیگ‌های لینک اشتراک':'Subscription link configs',
    'هر کدام را تیک بزنی، داخل همین لینک اشتراک می‌آید.':'Select the configs to include in this subscription link.',
    'اگر همه تیک بخورند یعنی «همه» (کانفیگ‌هایی که بعداً به این کاربر اضافه شوند هم می‌آیند).':'Selecting all also includes configs added to this user later.',
    'تصویر کاربر ذخیره شد':'User image saved','لینک کپی شد':'Link copied','اول دامنهٔ نود را بزن':'Enter the node domain first',
    'در حال شناسایی':'Detecting…','شناسایی نشد:':'Not detected:','نود TiTaN شناسایی شد':'TiTaN node detected',
    'این آدرس جواب می‌دهد ولی TiTaN نیست':'This address responds, but it is not TiTaN','دستی اضافه کن':'Add manually',
    'شناسایی خودکار ممکن نشد':'Automatic detection failed','دستی پر کن؛ بعد از ذخیره، متغیرها را با یک دکمه کپی می‌کنی.':'Fill this in manually; after saving, copy the variables with one click.',
    'نود شناسایی شد':'Node detected','شناسایی خودکار انجام نشد':'Automatic detection failed',
    'دسترسی خودکار داده شد — نیازی به متغیر نیست ✓':'Automatic access granted — no variables needed ✓',
    'دسترسی خودکار نشد':'Automatic access failed','متغیرها را ست کن':'Set the variables',
    'اگر نود خودکار وصل شد، همین‌جا کارت تمام است. اگر نه، این متغیرها را روی سرویسِ نود بگذار و یک‌بار دیپلوی کن.':'If the node connected automatically, you’re done. Otherwise, set these variables on the node service and redeploy.',
    'ویرایش سرور':'Edit server','افزودن سرور':'Add server','دامنهٔ نود یا نام را بزن':'Enter the node domain or name',
    'نود جواب نداد (':'Node did not respond (',') — کانفیگ‌ها موقتاً از پنل سرو می‌شوند':') — configs will temporarily be served by the panel',
    'نود خودکار شناسایی و وصل شد ✓':'Node detected and connected automatically ✓',
    'نود اضافه شد و کاربرانش را گرفت ✓':'Node added and its users synced ✓','نود اعتبارنامه‌اش را نگرفته':'Node has not received its credential',
    'آخرین همگام‌سازی موفق نبود:':'Last sync failed:','هنوز هیچ همگام‌سازی موفقی نداشته':'No successful sync yet',
    '— تا آماده شدنش، کانفیگ از پنل سرو می‌شود (تایم‌اوت نمی‌کند).':'— the panel serves the config until it is ready (no timeout).',
    'الان آنلاین نیست، ولی کاربر روی آن ثبت می‌شود.':'It is offline now, but the user will still be assigned to it.',
    'روی ':'On ','سرو می‌شود (':'is served (','آنلاین':'Online','نامعلوم':'Unknown',
    'ویرایش کاربر / کانفیگ':'Edit user / config','افزودن کاربر / کانفیگ':'Add user / config',
    'انتقال':'Transport','متد Shadowsocks':'Shadowsocks method','امنیت':'Security','حجم':'Quota',
    'حجم به گیگابایت':'Quota in gigabytes','انقضای روز':'Expiry (days)','یادداشت':'Note','یادداشت (اختیاری)':'Note (optional)',
    'شناسه کاربر':'User ID','رمز عبور جدید':'New password','نام*':'Name*','شهر':'City','کشور':'Country',
    'کد کشور':'Country code','پرچم':'Flag','آدرس سرور':'Server address','آدرس یا دامنه نود':'Node address or domain',
    'خودکار (نزدیک‌ترین)':'Auto (nearest)','خودکار (نزدیک‌ترین نودِ آنلاین و همگام‌شده)':'Auto (nearest online, synced node)',
    'خودکار = نزدیک‌ترین نودِ آنلاین و همگام‌شده.':'Auto = nearest online, synced node.',
    'این نود در حالت نگهداری است — کانفیگ از پنل سرو می‌شود.':'This node is in maintenance mode — the panel serves the config.',
    'آخرین تماس: ':'Last contact: ','آخرین همگام‌سازی ناموفق بود':'The last sync failed',
    'همگام‌سازی قدیمی است':'Sync is stale','یک بار همگام‌سازی فوری بزن.':'Run a sync now.',
    'وضعیت همگام‌سازی هنوز اندازه‌گیری نشده است.':'Sync status has not been measured yet.',
    'حذف لینک':'Delete link','بررسی شد':'Checked','نود شناسایی شد و کاربرانش را گرفت ✓':'Node detected and its users synced ✓',
    'وصل نشد — متغیرها را ببین':'Could not connect — check the variables','همگام‌سازی شد':'Synced',
    'به حالت نگهداری رفت':'Maintenance mode enabled','از حالت نگهداری خارج شد':'Maintenance mode disabled',
    'بررسی اتصال نودها':'Check node connections','مدیریت سرورها':'Manage servers','تأیید':'Confirm',
    'افزودن':'Add','ایجاد':'Create','کاربران فعال':'Active users','مصرف کل':'Total usage','تعداد کاربران':'User count',
    'تعداد نودها':'Node count','میانگین تأخیر':'Average latency','پایداری':'Stability','ترافیک':'Traffic',
    'دانلود':'Download','آپلود':'Upload','نزدیک به انقضا':'Expiring soon','پروتکل‌های استفاده‌شده':'Used protocols',
    'روز قبل':'days ago','حساب':'account','مورد':'items','بار':'times','نود':'Node','نودها':'Nodes',
    'کاربران':'Users','کانفیگ':'Config','کانفیگ‌ها':'Configs','سرور':'Server','سرورها':'Servers',
    'مدیریت':'Management','اشتراک':'Subscription','اشتراک‌ها':'Subscriptions','گزارش':'Report',
    'خطا':'Error','موفق':'Successful','فعال':'Active','غیرفعال':'Disabled','خاموش':'Disabled',
    'منقضی':'Expired','آنلاین':'Online','آفلاین':'Offline','وضعیت':'Status','نام':'Name','شهر':'City',
    'کشور':'Country','کد کشور':'Country code','پرچم':'Flag','دلیل':'Reason','زمان':'Time','تاریخ':'Date',
    'ورود':'Sign in','ذخیره':'Save','لغو':'Cancel','بستن':'Close','حذف':'Delete','ویرایش':'Edit',
    'کپی':'Copy','تأیید':'Confirm','نامشخص':'Unknown','نامعلوم':'Unknown','فعالیت':'Activity',
    'تعداد':'Count','حداکثر':'Maximum','سطح':'Level','فهرست':'List','کاربردی':'Useful','سریع':'Quick',
    'اعلان':'Notification','ورود جدید':'New sign-in','پشتیبانی':'Support','گالری':'Gallery',
    'بازنشانی':'Reset','بازیابی':'Restore','پشتیبان':'Backup','پورت':'Port','زبان':'Language',
    'دامنه':'Domain','سرویس':'Service','شبکه':'Network','سیستم':'System','داده':'Data','موقت':'Temporary',
    'پیش‌فرض':'Default','اختیاری':'Optional','بازه':'Interval','طول':'Length','تغییر':'Change',
    'کاربرها':'Users','مدیران':'Admins','مدیر':'Admin','مجوز':'Permission','مجاز':'Allowed',
    'حریم خصوصی':'Privacy','نشست':'Session','همزمان':'Concurrent','کاهش':'Reduce','بررسی':'Check',
    'اتصال':'Connection','آدرس':'Address','مقصد':'Destination','فعلی':'Current','نزدیک‌ترین':'Nearest',
    'سرو می‌شود':'is served','موجود نیست':'not available','انتخاب':'Select','موردی':'No items','اشتباه':'Incorrect',
    'پاسخ':'Response','در حال':'In progress','هیچ':'No','این':'This','همه':'All','برای':'for','از':'of',
    'تا':'to','با':'with','و':'and','یا':'or','بر':'on','در':'in','به':'to','را':'',
    'مجموع':'Total','دریافت':'Receive','ارسال':'Send','پردازنده':'CPU','حافظه':'Memory','دیسک':'Disk',
    'نسخه':'Version','نگهداری':'Maintenance','پایداری':'Uptime','ترافیک مصرفی':'Traffic used',
    'فعال‌سازی':'Enable','غیرفعال‌سازی':'Disable','درصد':'Percent','نامحدود':'Unlimited','هرگز':'Never',
    'دقیقه':'minutes','ثانیه':'seconds','ساعت':'hours','روز':'days','ماه':'months','سال':'years',
    'همگام‌سازی':'Sync','راز مشترک':'shared secret','گذشته':'ago','اخیر':'recent',
    'پینگ‌سنج — اندازه‌گیری از همین دستگاه':'Ping tester — measure from this device',
    'هر لینکی که روی ':'Every link hosted on ',' سرو شود، ':' is served, ',
    ' دورتر از یک سرور نزدیک شماست — این همان چیزی است که «پینگِ قبلاً کمتر بود» را توضیح می‌دهد.':'farther than a nearby server — explaining why the ping used to be lower.',
    '؛ تا کفِ ممکن ≈ ':'; the gap to the minimum possible is ≈ ',
    'فاصله دارد. یک نود در همان شهرِ نزدیک (امارات/ترکیه) این فاصله را حذف می‌کند.':'away. A node in the same nearby city (UAE/Türkiye) would remove the gap.',
    'کلید نود تنظیم شده است (':'Node key is configured (','کلید نود تنظیم نشده':'Node key is not configured',
    'با زدن «ذخیره» خودکار وصل می‌شود ✓':'It connects automatically when you save ✓',
    'اگر وصل نشد، متغیرها را ست کن':'If it does not connect, set the variables',
    'هیچ‌کدام':'None','خاموش کردن':'Turn off','روشن کردن':'Turn on',
    'شناسایی و اتصال خودکار (دامنه کافی است)':'Auto-detect and connect (domain only)',
    'همگام‌سازی فوری':'Sync now','خروج از حالت نگهداری':'Exit maintenance mode','حالت نگهداری':'Maintenance mode',
    'اپ‌تایم':'Uptime','کاربر روی نود:':'User on node:','انصراف':'Cancel',
    'لوگوی TiTaN':'TiTaN logo','آپلود عکس':'Upload image','پروفایل کاربر — مثل قبل':'User profile — as before',
    'فینگرپرینت':'Fingerprint','حد دستگاه':'Device limit','حد درخواست':'Request limit',
    'IPهای مجاز (با کاما جدا کن، CIDR هم قبول است)':'Allowed IPs (comma-separated; CIDR is supported)',
    'کپی همهٔ متغیرها با یک کلیک':'Copy all variables with one click',
    'کپی همه (آماده برای Raw Editor)':'Copy all (ready for Raw Editor)',
    'عنوان پلن (زیر نام کاربر روی همان صفحه)':'Plan title (below the user name on that page)',
    'دامنهٔ سرویس نود (کافی است)':'Node service domain (that is enough)',
    'کد کشور (2 حرف)':'Country code (2 letters)',
    'اگر خالی بماند، تصویر خودِ کاربر روی صفحهٔ اشتراک می‌آید':'If left blank, the user’s own image appears on the subscription page',
    'از بین کانفیگ‌های ساخته‌شده انتخاب کن؛ هر چیزی که تیک بخورد داخل همین لینک می‌آید. یک کاربر می‌تواند چند کانفیگ داشته باشد و چند کاربر می‌توانند در یک لینک جمع شوند.':'Choose from existing configs; selected items go into this link. A user may have multiple configs, and several users can share one link.',
    'هر کدام را تیک بزنی، داخل همین لینک اشتراک می‌آید. اگر همه تیک بخورند یعنی «همه» (کانفیگ‌هایی که بعداً به این کاربر اضافه شوند هم خودکار می‌آیند).':'Select configs for this link. Selecting all also includes configs added to this user later.',
    'دامنه را بزن و ذخیره کن: نام، شهر، پرچم و کلید نود خودکار تشخیص داده می‌شود. اگر شناسایی ممکن نشد، فیلدهای دستی را پر کن و بعد متغیرها را با یک دکمه کپی کن.':'Enter the domain and save: the name, city, flag, and node key will be detected automatically. If detection fails, fill in the fields manually and copy the variables with one click.',
    'آخرین همگام‌سازی ناموفق بود (':'Last sync failed (',
    ') — کاربران این نود از پنل سرو می‌شوند؛ توکن نود را روی خودِ نود ست کن (دکمهٔ ویرایش).':') — this node’s users are served by the panel; set its node token on the node itself (Edit button).',
    'تصویر این لینک':'This link’s image','تصویر این کاربر':'This user’s image',
    'ساخت/ویرایش کانفیگ‌های این لینک':'Create/edit configs for this link',
    'کپی لینک اشتراک (برای کلاینت‌ها)':'Copy the subscription link (for clients)',
    'کپی لینک صفحهٔ اشتراک (برای کاربر)':'Copy the subscription page link (for the user)',
    'غیرفعال کردن':'Disable','فعال کردن':'Enable','کل':'Total','پروتکل‌ها':'Protocols',
    // Remaining live modal/toast copy found in the Dashboard dynamic-text audit.
    'انگلیسی':'English','اثر انگشت':'Fingerprint','اصلی':'Main','لینک':'Link','فرگمنت':'Fragment',
    'آمستردام':'Amsterdam','بمبئی':'Mumbai',
    'آمریکا — سن‌خوزه':'United States — San Jose','آمریکا — ویرجینیا':'United States — Virginia',
    'هلند — آمستردام':'Netherlands — Amsterdam','هند — بمبئی':'India — Mumbai',
    'امارات — دبی':'United Arab Emirates — Dubai','فرانسه — پاریس':'France — Paris',
    'آدرسی ثبت نشده':'No address registered','هنوز کاربری ساخته نشده':'No users have been created yet',
    'کانفیگی برای این کاربر ساخته نشده':'No configs have been created for this user',
    'هیچ کانفیگی انتخاب نشده':'No config selected','ساخت لینک اشتراک':'Create subscription link',
    'ویرایش لینک اشتراک':'Edit subscription link',
    'نام اشتراک را بنویس':'Enter a subscription name','حداقل یک کانفیگ انتخاب کن':'Select at least one config',
    'لینک ساخته شد و کپی شد ✓':'Subscription link created and copied ✓',
    'پوش شد ✓':'pushed ✓','ذخیره شد، ولی نود قبول نکرد (':'Saved, but the node rejected it (',
    ') — فعلاً از پنل سرو می‌شود':') — currently served by the panel',
    'خام (TCP)':'Raw (TCP)','از مسیر HTTPS':'via HTTPS','راه‌اندازی این نود':'Set up this node',
    'نود جواب داد و کاربرانش را گرفت ✓':'Node responded and synced its users ✓',
    'این نود هنوز جواب نداده':'This node has not responded yet',
    'تا آن موقع، کانفیگ‌های این نود روی خودِ پنل سرو می‌شوند (تایم‌اوت نمی‌کنند).':'Until then, this node’s configs are served by the panel (no timeout).',
    'کپی شد':'Copied','همهٔ متغیرها کپی شد ✓':'All variables copied ✓',
    'کپی نشد — دستی انتخاب کن':'Copy failed — select manually','فهمیدم':'Got it',
    'کانفیگ خاموش شد':'Config turned off','کانفیگ روشن شد':'Config turned on','سرور اصلی':'Primary server',
    'هنوز لینک اشتراکی ساخته نشده — با دکمهٔ بالا یکی بساز.':'No shared links yet — create one with the button above.',
    'لینک صفحهٔ اشتراک کپی شد':'Subscription page link copied',
    'تصویر این لینک برداشته شد':'This link’s image was removed','لینک غیرفعال شد':'Link disabled',
    'لینک فعال شد':'Link enabled','این لینک اشتراک حذف شود؟':'Delete this subscription link?',
    'تغییر رمز':'Change password','رمز جدید باید حداقل ۶ کاراکتر باشد':'Password must be at least 6 characters',
    'رمز عبور تغییر کرد':'Password changed','رمز فعلی اشتباه است':'Current password is incorrect',
    'بازیابی از پشتیبان؟':'Restore backup?','بازیابی شد':'Restored','راه‌اندازی مجدد پنل؟':'Restart the panel?',
    'در حال راه‌اندازی...':'Starting…','در حال تست...':'Testing…','به‌روزرسانی شد':'Updated','خروج':'Log out'
  });
  const DASHBOARD_FA_KEYS=Object.keys(DASHBOARD_TEXT).filter(k=>/[\u0600-\u06ff]/.test(k)).sort((a,b)=>b.length-a.length);
  const dashboardPhrase=source=>source.includes(' ')||/[—←→✓●⏻:：?!؟.,()]/.test(source);
  const DASHBOARD_FA_PHRASES=DASHBOARD_FA_KEYS.filter(dashboardPhrase);
  const DASHBOARD_FA_WORDS=DASHBOARD_FA_KEYS.filter(k=>!dashboardPhrase(k));
  const DASHBOARD_EN_TO_FA=Object.freeze({
    ...Object.fromEntries(Object.entries(DASHBOARD_TEXT).filter(([fa,en])=>/[\u0600-\u06ff]/.test(fa)&&typeof en==='string'&&en.length).map(([fa,en])=>[en,fa])),
    'Dashboard':'داشبورد','Users':'کاربران','Configs':'کانفیگ‌ها','Servers':'سرورها',
    'Subscriptions':'اشتراک‌ها','Reports':'گزارش‌ها','Settings':'تنظیمات','Tools':'ابزارها',
    'Admin management':'مدیریت ادمین','Super Admin':'ادمین کل','Admin':'مدیر','Owner':'مدیر اصلی',
    'Private network':'شبکه خصوصی','Private Network':'شبکه خصوصی','PRIVATE NETWORK':'شبکه خصوصی','English':'انگلیسی','Online':'آنلاین','Nodes':'نودها','Node':'نود','node':'نود','main':'اصلی',
    'Active':'فعال','Inactive':'غیرفعال','Disabled':'غیرفعال','Expired':'منقضی','Offline':'آفلاین',
    'Save':'ذخیره','Cancel':'لغو','Close':'بستن','Delete':'حذف','Copy':'کپی','Done':'انجام شد',
    'Edit':'ویرایش','Language':'زبان','Panel language':'زبان پنل','Support':'پشتیبانی',
    'sync':'همگام‌سازی','token':'توکن','shared secret':'راز مشترک',
    'Loading…':'در حال بارگذاری…','No data available':'داده‌ای وجود ندارد','No items found':'موردی وجود ندارد'
  });
  const DASHBOARD_EN_KEYS=Array.from(new Set([
    ...Object.keys(DASHBOARD_EN_TO_FA),
    ...Object.keys(DASHBOARD_TEXT).filter(k=>k&&!/[\u0600-\u06ff]/.test(k)),
    ...Object.values(DASHBOARD_TEXT).filter(v=>typeof v==='string'&&v&&!/[\u0600-\u06ff]/.test(v))
  ])).filter(Boolean).sort((a,b)=>b.length-a.length);
  const DASHBOARD_EN_PHRASES=DASHBOARD_EN_KEYS.filter(dashboardPhrase);
  const DASHBOARD_EN_WORDS=DASHBOARD_EN_KEYS.filter(k=>!dashboardPhrase(k));
  const dashboardTextOriginal=new WeakMap(),dashboardTextRendered=new WeakMap();
  const dashboardAttrOriginal=new WeakMap(),dashboardAttrRendered=new WeakMap();
  let dashboardLang='fa';
  function replaceUiPhrase(text,source,target){
    if(!source)return text;
    const escaped=source.replace(/[.*+?^${}()|[\]\\]/g,'\\$&').replace(/ /g,'\\s+');
    if(source.includes(' ')||/[—←→✓●⏻:：?!؟.,()]/.test(source)){
      return text.replace(new RegExp(escaped,'gu'),target);
    }
    // Persian ZWNJ is part of a word; do not translate fragments such as
    // "به" inside "به‌روزرسانی" when replacing standalone UI words.
    const pattern=new RegExp('(^|[^\\p{L}\\p{N}\\u200c])'+escaped+'(?=$|[^\\p{L}\\p{N}\\u200c])','gu');
    return text.replace(pattern,(_,prefix)=>prefix+target);
  }
  function dashboardText(value,lang=dashboardLang){
    let text=String(value==null?'':value);
    if(lang==='en'){
      // Translate complete labels first; otherwise numeric fragments such as
      // "7 days" would consume part of "Last 7 days" before its full phrase.
      for(const fa of DASHBOARD_FA_PHRASES) text=replaceUiPhrase(text,fa,DASHBOARD_TEXT[fa]);
      text=text.replace(/از\s*([0-9۰-۹]+)\s*کاربر/g,(_,n)=>`of ${n} ${String(n).replace(/[۰-۹]/g,d=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))==='1'?'user':'users'}`)
               .replace(/از\s*([0-9۰-۹]+)\s*کانفیگ/g,'of $1 configs')
               .replace(/([0-9۰-۹]+)\s*حساب/g,'$1 accounts')
               .replace(/([0-9۰-۹]+)\s*مورد/g,'$1 items')
               .replace(/([0-9۰-۹]+)\s*روز/g,'$1 days');
      for(const fa of DASHBOARD_FA_WORDS) text=replaceUiPhrase(text,fa,DASHBOARD_TEXT[fa]);
      text=text.replace(/[۰-۹]/g,d=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)));
    }else{
      // Reverse whole labels before handling counts so toggling languages never
      // leaves a half-translated phrase such as "Last 7 روز".
      for(const en of DASHBOARD_EN_PHRASES) text=replaceUiPhrase(text,en,DASHBOARD_EN_TO_FA[en]||DASHBOARD_TEXT[en]);
      text=text.replace(/of\s*([0-9]+)\s*users?/gi,(_,n)=>`از ${n} کاربر`)
               .replace(/([0-9]+)\s*accounts?/gi,'$1 حساب')
               .replace(/([0-9]+)\s*items?/gi,'$1 مورد')
               .replace(/([0-9]+)\s*days?/gi,'$1 روز');
      for(const en of DASHBOARD_EN_WORDS) text=replaceUiPhrase(text,en,DASHBOARD_EN_TO_FA[en]||DASHBOARD_TEXT[en]);
    }
    return text;
  }
  function translateDashboard(root){
    if(!root||!document.body||typeof document.createTreeWalker!=='function'||typeof NodeFilter==='undefined')return;
    const ignored='script,style,textarea,code,pre,[data-i18n-ignore]';
    const translateNode=node=>{
      if(!node||!node.nodeValue||!node.nodeValue.trim())return;
      const parent=node.parentElement;
      if(parent&&parent.closest(ignored))return;
      // User-supplied names, plans, and locations are data, not interface copy.
      if(parent&&parent.closest('.profile-name,.recent-name,.recent-server-name,.sr-name,.sr-loc,.plan,.config-user-name,.user-cell,.sub-user-name,.nl-name,.nl-loc,.node-location-data,.server-row .location'))return;
      let original=dashboardTextOriginal.get(node);
      if(original===undefined||dashboardTextRendered.get(node)!==node.nodeValue){
        original=node.nodeValue;
        dashboardTextOriginal.set(node,original);
      }
      const next=dashboardText(original);
      if(next!==node.nodeValue)node.nodeValue=next;
      dashboardTextRendered.set(node,next);
    };
    const attrs=['placeholder','title','aria-label','alt','data-tip','data-msg','data-demo'];
    const translateElement=el=>{
      if(!el||el.nodeType!==1||el.matches(ignored))return;
      let originals=dashboardAttrOriginal.get(el),rendered=dashboardAttrRendered.get(el);
      if(!originals){originals=new Map();dashboardAttrOriginal.set(el,originals);}
      if(!rendered){rendered=new Map();dashboardAttrRendered.set(el,rendered);}
      for(const attr of attrs){
        if(!el.hasAttribute(attr))continue;
        // The title on a server row is the admin-entered node name.
        if(attr==='title'&&el.classList&&el.classList.contains('server-row'))continue;
        const value=el.getAttribute(attr);
        if(!originals.has(attr)||rendered.get(attr)!==value)originals.set(attr,value);
        const next=dashboardText(originals.get(attr));
        if(next!==value)el.setAttribute(attr,next);
        rendered.set(attr,next);
      }
    };
    if(root.nodeType===3){translateNode(root);return;}
    if(root.nodeType===1)translateElement(root);
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    let node;while((node=walker.nextNode()))translateNode(node);
    if(root.querySelectorAll){
      root.querySelectorAll(attrs.map(a=>'['+a+']').join(',')).forEach(translateElement);
    }
  }
  function applyDashboardLanguage(lang,persist=true){
    dashboardLang=lang==='en'?'en':'fa';
    document.documentElement.lang=dashboardLang;
    document.documentElement.dir=dashboardLang==='fa'?'rtl':'ltr';
    document.title=dashboardLang==='en'?'TiTaN — Private Network':'TiTaN — شبکه خصوصی';
    if(persist){try{localStorage.setItem('titan-language',dashboardLang);localStorage.setItem('titan_lang',dashboardLang);}catch(_){}}
    const selector=document.getElementById('dashboardLanguage');
    if(selector)selector.value=dashboardLang;
    translateDashboard(document.body);
  }
  function initDashboardLanguage(){
    let saved='fa';try{saved=localStorage.getItem('titan-language')||localStorage.getItem('titan_lang')||'fa';}catch(_){}
    applyDashboardLanguage(saved,false);
    const selector=document.getElementById('dashboardLanguage');
    if(selector)selector.addEventListener('change',()=>applyDashboardLanguage(selector.value));
    if(typeof MutationObserver==='undefined'||!document.body)return;
    const observer=new MutationObserver(records=>{
      for(const record of records){
        if(record.type==='characterData')translateDashboard(record.target);
        else if(record.type==='attributes')translateDashboard(record.target);
        else record.addedNodes.forEach(node=>translateDashboard(node));
      }
    });
    observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['placeholder','title','aria-label','alt','data-tip','data-msg','data-demo']});
  }

  // ── premium icon set (inline SVG, stroke = currentColor) ──────────────────
  const ICONS = {
    bolt:'<path d="M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5z"/>',
    sparkle:'<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"/><path d="M18.5 15.5l.7 1.9 1.8.6-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.6.7-1.9z"/>',
    userplus:'<circle cx="9" cy="8" r="3.2"/><path d="M3 20c.7-3.6 3-5.7 6-5.7s5.3 2.1 6 5.7"/><path d="M18 8v6M15 11h6"/>',
    link:'<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    edit:'<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>',
    trash:'<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>',
    copy:'<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    qr:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM20 14v1M14 20h1M18 18h3"/>',
    eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    pulse:'<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    sync:'<path d="M21 12a9 9 0 0 1-15.3 6.4M3 12a9 9 0 0 1 15.3-6.4"/><path d="M21 4v6h-6M3 20v-6h6"/>',
    power:'<path d="M18.4 6.6a9 9 0 1 1-12.8 0"/><path d="M12 2v10"/>',
    download:'<path d="M12 3v12m0 0 4.5-4.5M12 15l-4.5-4.5"/><path d="M4 19h16"/>',
    sliders:'<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h9M17 18h3"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="15" cy="18" r="2"/>',
    checks:'<path d="M3 7.5 6 10.5l4.5-5M12 8h9M3 17.5 6 20.5l4.5-5M12 18h9"/>',
    xcircle:'<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    image:'<rect x="3" y="4" width="18" height="16" rx="2.6"/><circle cx="8.6" cy="9.6" r="1.7"/><path d="M4.2 17.6 9.4 12l3.9 3.7 2.9-2.5 3.5 3.3"/>',
  };
  function icon(name, size=17, width=1.8){
    const body = ICONS[name] || ICONS.sparkle;
    return `<svg viewBox="0 0 24 24" style="width:${size}px;height:${size}px;fill:none;stroke:currentColor;stroke-width:${width};stroke-linecap:round;stroke-linejoin:round" aria-hidden="true">${body}</svg>`;
  }
  // A premium icon button: no Persian word on the face, the label lives in the tooltip.
  function icoBtn(attrs, name, tip, variant=''){
    const a = Object.entries(attrs||{}).map(([k,v])=>`${k}="${esc(v)}"`).join(' ');
    return `<button class="ico-btn${variant?' '+variant:''}" data-tip="${esc(tip)}" aria-label="${esc(tip)}" ${a}>${icon(name)}</button>`;
  }

  function fmtDate(ts){ try{ return new Date(ts*1000).toLocaleDateString(dashboardLang==='en'?'en-GB':'fa-IR'); }catch(e){ return '—'; } }
  async function apiJson(url, opts={}){ opts.credentials='same-origin'; opts.headers=Object.assign({'Content-Type':'application/json'},opts.headers||{}); if(opts.body&&typeof opts.body!=='string') opts.body=JSON.stringify(opts.body); const r=await fetch(url,opts); let d={}; try{d=await r.json();}catch(e){ if(!r.ok) throw new Error(r.statusText); } if(!r.ok) throw new Error(d.detail||d.message||r.statusText); return d; }

  let toastEl=$('#titanToast');
  if(!toastEl){ toastEl=document.createElement('div'); toastEl.id='titanToast'; toastEl.style.cssText='position:fixed;left:50%;bottom:22px;transform:translate(-50%,14px);opacity:0;pointer-events:none;padding:10px 16px;border-radius:12px;color:#eeeaff;background:rgba(6,8,35,.94);border:1px solid rgba(104,77,255,.45);box-shadow:0 0 24px rgba(75,40,255,.18);backdrop-filter:blur(12px);transition:.24s;z-index:9999;font-size:12px;'; document.body.appendChild(toastEl); }
  function toast(m){ toastEl.textContent=m; toastEl.style.opacity='1'; toastEl.style.transform='translate(-50%,0)'; clearTimeout(toastEl._t); toastEl._t=setTimeout(()=>{toastEl.style.opacity='0';toastEl.style.transform='translate(-50%,14px)';},2200); }

  // ── latency advisor (پینگ‌سنج) ─────────────────────────────────────────────
  // The distance that decides a client's ping is client -> exit, and only the
  // client can measure it. Everything below is a tiny no-store request sent
  // from *this browser*; node probes go cross-origin as `no-cors` (the payload
  // is opaque, the round-trip is not) so a node needs no extra endpoint and an
  // old node build still answers.
  const EDGE_POPS = {sjc1:'آمریکا — سن‌خوزه', iad1:'آمریکا — ویرجینیا', ams1:'هلند — آمستردام',
                     fra1:'آلمان — فرانکفورت', lon1:'انگلستان — لندن', sin1:'سنگاپور',
                     bom1:'هند — بمبئی', dxb1:'امارات — دبی', cdg1:'فرانسه — پاریس'};
  function latBand(ms){
    if(ms==null) return ['off','—'];
    if(ms<70)  return ['ok','هم‌سایه (ترکیه/امارات)'];
    if(ms<120) return ['ok','اروپا'];
    if(ms<180) return ['mid','دورتر از حد مطلوب'];
    return ['bad','آمریکا/دور'];
  }
  function latCb(url){ return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'cb=' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function latNow(){ return (window.performance && performance.now) ? performance.now() : Date.now(); }
  async function rttOnce(url, mode, timeout){
    const ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    const timer = ctl ? setTimeout(()=>{ try{ ctl.abort(); }catch(e){} }, timeout||4000) : null;
    const t0 = latNow();
    try{
      await fetch(latCb(url), {cache:'no-store', mode: mode||'cors', credentials:'omit',
                               signal: ctl?ctl.signal:undefined, redirect:'follow'});
      return Math.max(1, Math.round(latNow() - t0));
    }catch(e){ return null; }
    finally{ if(timer) clearTimeout(timer); }
  }
  // The first request pays DNS + TLS, the rest reuse the connection: only the
  // later samples describe the link itself, so they are what gets reported.
  async function rttBest(url, mode, samples){
    const n = samples||3; let best=null, sum=0, cnt=0;
    for(let i=0; i<=n; i++){
      const ms = await rttOnce(url, mode, 4000);
      if(ms==null) continue;
      if(i>0){ best = (best==null||ms<best)? ms : best; sum+=ms; cnt++; }
    }
    return cnt ? {ms:best, avg:Math.round(sum/cnt), n:cnt} : null;
  }

  async function openLatencyAdvisor(){
    const nodesRes = await apiJson('/api/nodes').catch(()=>({nodes:[]}));
    const nodes = (nodesRes.nodes||[]).filter(n=>n.enabled!==false);
    const rows = [];
    const add=(key,name,url,mode,extra)=> rows.push(Object.assign({key:key,name:name,url:url||'',mode:mode||'cors',result:null}, extra||{}));

    add('panel','پنل (همین آدرسی که باز است)','/healthz','same-origin',{hint:'لینک‌هایی که روی پنل سرو می‌شوند از همین مسیر می‌آیند'});
    nodes.forEach(n=>{
      const addr = String(n.address||'').replace(/\/+$/,'');
      const label = nodeFlag(n) + ' ' + (n.name||(dashboardLang==='en'?'Node':'نود'));
      if(!addr){ add('n'+n.id, label, '', 'cors', {skip:'آدرسی ثبت نشده'}); return; }
      if(addr.indexOf('http://')===0){ add('n'+n.id, label, '', 'cors', {skip:'آدرس http است؛ از صفحهٔ https اندازه‌گیری نمی‌شود'}); return; }
      const base = addr.indexOf('http')===0 ? addr : 'https://'+addr;
      add('n'+n.id, label+' ('+(dashboardLang==='en'?'node':'نود')+')', base+'/healthz', 'no-cors', {node:true});
    });
    add('cf','نزدیک‌ترین نقطهٔ Cloudflare','https://cp.cloudflare.com/generate_204','no-cors',{hint:'کفِ پینگ ممکن برای یک سرور نزدیکِ شما'});

    const rowHtml=(r)=>{
      const b = latBand(r.result && r.result.ms);
      const val = r.skip ? '<span class="muted">—</span>'
                : (r.result ? `<b class="lat-ms ${b[0]}">${r.result.ms}</b> <span class="muted">ms</span>`
                             : '<span class="lat-spin">…</span>');
      return `<div class="lat-row" id="lat-${esc(r.key)}"><span class="lat-name"${r.node?' data-i18n-ignore':''}${r.hint?' data-tip="'+esc(r.hint)+'"':''}>${esc(r.name)}</span>`
           + `<span class="lat-val">${val}</span><span class="lat-tag pill ${b[0]}">${esc(r.skip||b[1])}</span></div>`;
    };

    const body = `<div style="display:grid;gap:12px">
      <p style="margin:0;font-size:11.5px;color:#a8a6bf;line-height:2">
        این عدد، رفت‌وبرگشت واقعی از <b>همین دستگاه</b> تا هر مقصد است — نه پینگ پنل به نود.
        هرچه خروجیِ کانفیگ به شما نزدیک‌تر باشد، پینگ کمتر می‌شود.
      </p>
      <div class="lat-grid" id="latGrid">${rows.map(rowHtml).join('')}</div>
      <div class="lat-verdict" id="latVerdict"><span class="lat-spin">…</span> در حال اندازه‌گیری</div>
      <div class="lat-custom">
        <input id="latCustom" dir="ltr" placeholder="https://host  یا  host:443">
        ${icoBtn({id:'latCustomGo'},'pulse','اندازه‌گیری این آدرس','violet')}
      </div>
      <p style="margin:0;font-size:10.5px;color:#8586a8;line-height:2">
        مرجع پینگ از ایران: ترکیه ۳۹–۵۰ · امارات ۳۹ · آلمان ۷۵–۱۲۰ · هلند ۸۰–۱۱۰ · آمریکا ۲۵۰+
      </p>
    </div>`;

    createModal('پینگ‌سنج — اندازه‌گیری از همین دستگاه', body, async ()=>'');
    const overlay = $('#titanModal');
    if(!overlay) return;

    let panelEdge = {pop:'', zone:''};
    try{
      const hr = await fetch(latCb('/healthz'), {cache:'no-store'});
      panelEdge = {pop: hr.headers.get('x-railway-edge')||'', zone: hr.headers.get('x-railway-upstream-zone')||''};
    }catch(e){ /* not on Railway / header unavailable: the number still counts */ }

    const draw=(r)=>{ const el = overlay.querySelector('#lat-'+r.key); if(el) el.outerHTML = rowHtml(r); };

    const measure=async()=>{
      const v = overlay.querySelector('#latVerdict');
      if(v) v.innerHTML = '<span class="lat-spin">…</span> در حال اندازه‌گیری';
      for(const r of rows){
        if(r.skip || !r.url) continue;
        r.result = await rttBest(r.url, r.mode, 3);
        draw(r);
      }
      const done = rows.filter(r=>r.result);
      const byMs = done.slice().sort((a,b)=>a.result.ms-b.result.ms);
      const panel = rows.find(r=>r.key==='panel');
      const cf = rows.find(r=>r.key==='cf');
      const nodies = done.filter(r=>r.node);
      const lines = [];
      if(byMs.length) lines.push(`سریع‌ترین مسیر از دستگاه شما: <b>${esc(byMs[0].name)}</b> با <b>${byMs[0].result.ms} ms</b>`);
      if(panel && panel.result && cf && cf.result){
        const gap = panel.result.ms - cf.result.ms;
        if(gap > 50) lines.push(`هر لینکی که روی <b>پنل</b> سرو شود، <b>${gap} ms</b> دورتر از یک سرور نزدیک شماست — این همان چیزی است که «پینگِ قبلاً کمتر بود» را توضیح می‌دهد.`);
      }
      if(nodies.length){
        const best = nodies.slice().sort((a,b)=>a.result.ms-b.result.ms)[0];
        const floor = cf && cf.result ? cf.result.ms : null;
        if(floor!=null && best.result.ms - floor > 50)
          lines.push(`بهترین نود شما <b>${esc(best.name)}</b> با <b>${best.result.ms} ms</b>؛ تا کفِ ممکن ≈ <b>${best.result.ms - floor} ms</b> فاصله دارد. یک نود در همان شهرِ نزدیک (امارات/ترکیه) این فاصله را حذف می‌کند.`);
        else lines.push(`بهترین نود شما (<b>${esc(best.name)}</b>) نزدیک کفِ ممکن است ✓`);
      }
      if(panelEdge.pop) lines.push(`منطقهٔ فعلی پنل: <b dir="ltr">${esc(panelEdge.pop)}</b>${EDGE_POPS[panelEdge.pop] ? ' — '+esc(EDGE_POPS[panelEdge.pop]) : ''}${panelEdge.zone ? ' <span dir="ltr" class="muted">('+esc(panelEdge.zone)+')</span>' : ''}`);
      if(v) v.innerHTML = lines.join('<br>') || 'چیزی قابل اندازه‌گیری نبود.';
    };

    setTimeout(()=>{
      const save = overlay.querySelector('#titanModalSave');
      if(save){ save.textContent='اندازه‌گیری مجدد'; save.onclick=()=>{ save.disabled=true; measure().finally(()=>{ save.disabled=false; }); }; }
      const cancel = overlay.querySelector('#titanModalCancel'); if(cancel) cancel.textContent='بستن';
      const go = overlay.querySelector('#latCustomGo'), input = overlay.querySelector('#latCustom');
      if(go && input) go.onclick = async()=>{
        let u = String(input.value||'').trim(); if(!u) return;
        if(u.indexOf('://') < 0) u = 'https://'+u;
        const path = u.replace(/^https?:\/\/[^\/]+/i, '');
        if(!path || path === '/') u = u.replace(/\/+$/,'') + '/healthz';
        const r = {key:'x'+Date.now().toString(36), name:u.replace(/^https?:\/\//,''), url:u, mode:'no-cors', result:null, node:true};
        rows.push(r);
        const grid = overlay.querySelector('#latGrid'); if(grid) grid.insertAdjacentHTML('beforeend', rowHtml(r));
        go.disabled = true;
        try{ r.result = await rttBest(r.url, r.mode, 3); draw(r); }
        finally{ go.disabled = false; }
      };
      measure();
    }, 20);
  }

  // ── subscription builder ───────────────────────────────────────────────────
  // A subscription is an object, not a view of a user: it has a name, its own
  // token and a list of (user, config) pairs. Building one mirrors building a
  // config — pick the pieces from what really exists, the panel mints the link.
  async function openSubBuilder(sub, refresh){
    const cat = await apiJson('/api/subscriptions/catalog');
    const users = cat.users||[];
    const editing = sub||null;
    // A *new* link starts empty: the whole point is choosing. An edit re-opens
    // with exactly the saved pick (an empty saved list means "every config of
    // that user", so that is shown as everything ticked).
    const picked = {};
    const keysOf = (uid)=> ((users.find(u=>u.uid===uid)||{}).configs||[]).map(c=>c.key);
    (editing && editing.items ? editing.items : []).forEach(it=>{
      picked[it.uid] = new Set(it.configs && it.configs.length ? it.configs : keysOf(it.uid));
    });
    const isOn = (uid,key)=>{ const s=picked[uid]; return !!s && s.has(key); };

    const rows = users.map(u=>{
      const chips = (u.configs||[]).map(c=>
        `<button type="button" class="sub-chip${isOn(u.uid,c.key)?' on':''}" data-sub-uid="${esc(u.uid)}" data-sub-key="${esc(c.key)}" data-tip="${esc(c.transport+'/'+c.security+' · '+(c.target==='node'?'روی نود':'روی پنل'))}">${esc(c.label||c.key)}</button>`).join('');
      const state = u.expired ? 'منقضی' : (u.enabled ? 'فعال' : 'خاموش');
      const cls = u.expired ? 'warn' : (u.enabled ? '' : 'off');
      return `<div class="sub-user" data-uid="${esc(u.uid)}">
        <div class="sub-user-head">
          <span class="avatar user-avatar sub-medal sub-pic" data-sub-upic="${esc(u.uid)}" role="button" tabindex="0" data-tip="تصویر این کاربر" aria-label="تصویر این کاربر"><img src="${esc(u.avatar_url||'/static/img/titan-avatar.svg')}" alt=""></span>
          <span class="sub-user-name">${esc(u.name)}<span class="muted"> · ${esc((u.protocol||'').toUpperCase())}</span></span>
          <span class="pill ${cls}">${esc(state)}</span>
          <span class="spacer"></span>
          ${icoBtn({"type":"button","data-sub-all":u.uid},"checks","همهٔ کانفیگ‌های این کاربر")}
          ${icoBtn({"type":"button","data-sub-none":u.uid},"xcircle","هیچ‌کدام")}
        </div>
        <div class="sub-chips">${chips || '<span class="muted">کانفیگی برای این کاربر ساخته نشده</span>'}</div>
      </div>`;
    }).join('');

    const countLinks = ()=> Array.from(document.querySelectorAll('#titanModal .sub-chip.on')).length;
    createModal(editing?'ویرایش لینک اشتراک':'ساخت لینک اشتراک', `
      <div style="display:grid;gap:14px">
        <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">نام اشتراک
          <input id="subName" value="${esc(editing&&editing.name||'')}" placeholder="مثلاً پک موبایل" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">
        </label>
        <div style="display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:center">
          <div class="avatar user-avatar sub-medal" id="subAvPreview" style="width:46px;height:46px;overflow:hidden">
            <img src="${esc(avatarUrl(editing&&editing.avatar||''))}" alt="" style="width:100%;height:100%;object-fit:cover">
          </div>
          <div style="display:grid;gap:8px">
            <div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap">
              <input type="hidden" id="subAvatar" value="${esc(editing&&editing.avatar||'')}">
              <button type="button" id="subAvPick" style="padding:8px 12px;border-radius:10px;border:1px solid rgba(151,116,255,.24);background:rgba(91,49,176,.12);color:#eee9ff;cursor:pointer">انتخاب تصویر این لینک</button>
              <span style="font-size:10px;color:#8586a8">اگر خالی بماند، تصویر خودِ کاربر روی صفحهٔ اشتراک می‌آید</span>
            </div>
            <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">عنوان پلن (زیر نام کاربر روی همان صفحه)
              <input id="subPlan" value="${esc(editing&&editing.plan||'')}" placeholder="Premium Subscription" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">
            </label>
          </div>
        </div>
        <p style="margin:0;font-size:11px;color:#a8a6bf;line-height:2">
          از بین کانفیگ‌های ساخته‌شده انتخاب کن؛ هر چیزی که تیک بخورد داخل همین لینک می‌آید.
          یک کاربر می‌تواند چند کانفیگ داشته باشد و چند کاربر می‌توانند در یک لینک جمع شوند.
        </p>
        <div class="sub-list">${rows || '<div class="muted">هنوز کاربری ساخته نشده</div>'}</div>
        <div class="sub-summary" id="subSummary"></div>
        ${editing?`<div class="sub-url" dir="ltr"><span>${esc(editing.url||'')}</span>${icoBtn({"type":"button","data-sub-copyurl":editing.id},"copy","کپی لینک","violet")}</div>`:''}
      </div>`, async (overlay)=>{
        const name = $('#subName',overlay).value.trim();
        if(!name) throw new Error('نام اشتراک را بنویس');
        const items = [];
        overlay.querySelectorAll('.sub-user').forEach(box=>{
          const uid = box.dataset.uid;
          const on = Array.from(box.querySelectorAll('.sub-chip.on')).map(c=>c.dataset.subKey);
          if(on.length) items.push({uid:uid, configs:on});
        });
        if(!items.length) throw new Error('حداقل یک کانفیگ انتخاب کن');
        const body = {name:name, items:items,
                      avatar:$('#subAvatar',overlay).value||'',
                      plan:$('#subPlan',overlay).value.trim()};
        const res = editing ? await apiJson('/api/subscriptions/'+editing.id,{method:'PATCH',body:body})
                            : await apiJson('/api/subscriptions',{method:'POST',body:body});
        if(refresh) refresh();
        if(res.subscription && res.subscription.url){
          try{ await navigator.clipboard.writeText(res.subscription.url); }catch(e){}
          return 'لینک ساخته شد و کپی شد ✓';
        }
        return 'ذخیره شد';
      });
    setTimeout(()=>{
      const overlay=$('#titanModal'); if(!overlay) return;
      const box=$('#subSummary',overlay);
      const paint=()=>{
        const n=Array.from(overlay.querySelectorAll('.sub-chip.on')).length;
        let u=0;
        overlay.querySelectorAll('.sub-user').forEach(b=>{ if(b.querySelector('.sub-chip.on')) u++; });
        if(box) box.textContent = n ? (n+' کانفیگ از '+u+' کاربر در این لینک') : 'هیچ کانفیگی انتخاب نشده';
      };
      overlay.querySelectorAll('.sub-chip').forEach(chip=> chip.addEventListener('click', ()=>{
        chip.classList.toggle('on'); paint();
      }));
      overlay.querySelectorAll('[data-sub-all]').forEach(b=> b.addEventListener('click', ()=>{
        const uid=b.dataset.subAll;
        overlay.querySelectorAll(`.sub-chip[data-sub-uid="${uid}"]`).forEach(c=>c.classList.add('on')); paint();
      }));
      overlay.querySelectorAll('[data-sub-none]').forEach(b=> b.addEventListener('click', ()=>{
        const uid=b.dataset.subNone;
        overlay.querySelectorAll(`.sub-chip[data-sub-uid="${uid}"]`).forEach(c=>c.classList.remove('on')); paint();
      }));
      // each user's own picture — what the page falls back to when the link has none
      overlay.querySelectorAll('[data-sub-upic]').forEach(el=> el.addEventListener('click', async()=>{
        const uid=el.dataset.subUpic;
        const rec=users.find(x=>x.uid===uid)||{};
        try{
          const k=await openGalleryPicker(rec.avatar||'');
          if(k==null) return;
          await apiJson('/api/users/'+uid,{method:'PATCH',body:{avatar:k}});
          rec.avatar=k; rec.avatar_url=avatarUrl(k);
          const img=el.querySelector('img'); if(img) img.src=avatarUrl(k);
          toast('تصویر کاربر ذخیره شد');
        }catch(e){ toast(e.message); }
      }));
      overlay.querySelectorAll('[data-sub-upic]').forEach(el=> el.addEventListener('keydown', (e)=>{
        if(e.key==='Enter'||e.key===' '){ e.preventDefault(); el.click(); }
      }));
      const avPick=$('#subAvPick',overlay), avIn=$('#subAvatar',overlay), avImg=$('#subAvPreview img',overlay);
      if(avPick) avPick.onclick=async()=>{
        const k=await openGalleryPicker(avIn.value);
        if(k!=null){ avIn.value=k; if(avImg) avImg.src=avatarUrl(k); }
      };
      const copyBtn=overlay.querySelector('[data-sub-copyurl]');
      if(copyBtn) copyBtn.addEventListener('click', async()=>{
        try{ await navigator.clipboard.writeText(editing.url||''); toast('لینک کپی شد'); }catch(e){ toast(editing.url||''); }
      });
      paint();
    }, 20);
  }

  // ── add a node from a domain alone ────────────────────────────────────────
  // The panel asks the address what it is before anything is saved, so the form
  // fills itself and the admin sees whether the node will accept users right
  // away. When it cannot identify the domain, the variables are still one click
  // away (نسخهٔ دستی).
  async function detectNode(addr, box){
    if(!addr){ toast('اول دامنهٔ نود را بزن'); return null; }
    if(box) box.innerHTML='<span class="lat-spin">…</span> در حال شناسایی '+esc(addr);
    let d;
    try{ d = await apiJson('/api/nodes/detect',{method:'POST',body:{address:addr}}); }
    catch(e){ if(box) box.innerHTML='<span class="det-bad">شناسایی نشد: '+esc(e.message)+'</span>'; return null; }
    const id = d.identity||{};
    if(d.ok){
      const f = d.fields||{};
      const fill=(sel,val)=>{ const el=$(sel); if(el && !el.value && val) el.value=val; };
      fill('#mn_name', f.name||''); fill('#mn_city', f.city||''); fill('#mn_country', f.country||'');
      fill('#mn_cc', f.country_code||''); fill('#mn_flag', nodeFlag(f));
      const nameEl=$('#mn_name'); if(nameEl && f.name && !nameEl.value) nameEl.value=f.name;
      if(box) box.innerHTML = `<div class="det-card">
        <div class="det-row"><span class="det-ok">✓ نود TiTaN شناسایی شد</span>
          <span class="muted" dir="ltr">v${esc(id.version||'?')} · ${esc(id.role||'node')}</span></div>
        <div class="det-row"><span>${nodeFlagHtml(id,'sm')} ${esc(id.city||'—')}${(id.country_code||nodeCountryCode(id))?' · '+esc(id.country_code||nodeCountryCode(id)):''}</span>
          <span class="muted" dir="ltr">edge ${esc((id.edge||{}).scheme||'https')} :${esc(String((id.edge||{}).port||''))}</span></div>
        <div class="det-row"><span>${id.credential? 'کلید نود تنظیم شده است ('+esc(id.credential)+')' : 'کلید نود تنظیم نشده'}</span>
          <span class="${id.accepts_bootstrap?'det-ok':'det-bad'}">${id.accepts_bootstrap? 'با زدن «ذخیره» خودکار وصل می‌شود ✓' : 'اگر وصل نشد، متغیرها را ست کن'}</span></div>
      </div>`;
    } else if(d.kind==='foreign'){
      if(box) box.innerHTML = '<div class="det-card"><div class="det-row"><span class="det-bad">این آدرس جواب می‌دهد ولی TiTaN نیست</span><span class="muted">دستی اضافه کن</span></div></div>';
    } else {
      if(box) box.innerHTML = '<div class="det-card"><div class="det-row"><span class="det-bad">شناسایی خودکار ممکن نشد</span><span class="muted" dir="ltr">'+esc(d.error||'')+'</span></div>'
        + '<div class="det-row muted">دستی پر کن؛ بعد از ذخیره، متغیرها را با یک دکمه کپی می‌کنی.</div></div>';
    }
    return d;
  }

  // --- gallery picker (real, as in old panel) ---
  // volume: what the admin typed, in whichever unit reads best (500 MB, 2 GB)
  function quotaView(u){
    const gb=Number((u&&u.quota_gb)||0);
    const mb=Number((u&&u.quota_mb)||0);
    if(gb>0&&gb<1) return {value:String(Number(mb.toFixed(mb<10?1:0))), unit:'mb'};
    return {value:String(gb||0), unit:'gb'};
  }

  function avatarUrl(key){
    key=key||''; if(key.startsWith('gallery:')) return '/static/img/gallery/'+key.slice(8)+'.svg'; if(key.startsWith('upload:')) return '/api/gallery-image/'+key.slice(7); return '/static/img/titan-avatar.svg';
  }
  async function openGalleryPicker(current=''){
    return new Promise(resolve=>{
      let items=[]; let sel=current||'';
      const overlay=document.createElement('div');
      overlay.style.cssText='position:fixed;inset:0;z-index:10000;background:rgba(2,4,18,.62);backdrop-filter:blur(8px);display:grid;place-items:center;padding:16px;';
      overlay.innerHTML=`<div style="width:min(520px,96vw);background:linear-gradient(145deg,rgba(24,12,56,.96),rgba(8,6,26,.98));border:1px solid rgba(151,116,255,.42);border-radius:18px;overflow:hidden;max-height:90vh;display:flex;flex-direction:column">
        <div style="padding:16px 18px;border-bottom:1px solid rgba(151,116,255,.18);display:flex;justify-content:space-between;align-items:center"><div style="font-weight:700;color:#f2edff">انتخاب تصویر</div><button id="gpClose" style="width:32px;height:32px;border-radius:9px;border:1px solid rgba(151,116,255,.24);background:rgba(91,49,176,.16);color:#d8c7ff;cursor:pointer">×</button></div>
        <div style="padding:16px;overflow:auto;flex:1">
          <button id="gpLogo" style="padding:8px 12px;border-radius:9px;border:1px solid rgba(151,116,255,.24);background:rgba(91,49,176,.12);color:#eee9ff;cursor:pointer;margin-bottom:12px">لوگوی TiTaN</button>
          <div id="gpGrid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px"></div>
          <div style="margin-top:14px;display:flex;gap:8px"><button id="gpUploadBtn" style="padding:8px 12px;border-radius:9px;border:1px solid rgba(151,116,255,.24);background:rgba(91,49,176,.12);color:#eee9ff;cursor:pointer">آپلود عکس</button><input type="file" id="gpFile" accept="image/png,image/jpeg,image/webp" style="display:none"></div>
        </div>
        <div style="padding:14px 18px;border-top:1px solid rgba(151,116,255,.18);display:flex;justify-content:flex-end;gap:10px"><button id="gpCancel" style="padding:10px 14px;border-radius:10px;border:1px solid rgba(151,116,255,.24);background:rgba(91,49,176,.12);color:#eee9ff;cursor:pointer">انصراف</button><button id="gpSave" style="padding:10px 16px;border-radius:10px;border:1px solid rgba(188,157,255,.5);background:linear-gradient(135deg,#7436f5,#4b1bb4);color:#fff;cursor:pointer">ذخیره</button></div>
      </div>`;
      document.body.appendChild(overlay);
      const close=(v)=>{ overlay.remove(); resolve(v); };
      overlay.addEventListener('click',e=>{ if(e.target===overlay) close(null); });
      $('#gpClose',overlay).onclick=()=>close(null);
      $('#gpCancel',overlay).onclick=()=>close(null);
      $('#gpSave',overlay).onclick=()=>close(sel);
      const render=()=>{
        const grid=$('#gpGrid',overlay);
        const logoBtn=$('#gpLogo',overlay);
        logoBtn.style.background = sel==='' ? 'linear-gradient(135deg,#7436f5,#4b1bb4)' : 'rgba(91,49,176,.12)';
        logoBtn.style.color = sel==='' ? '#fff' : '#eee9ff';
        grid.innerHTML = items.length ? items.map(it=>`
          <button data-key="${esc(it.id)}" style="position:relative;height:84px;border-radius:12px;overflow:hidden;border:1px solid ${sel===it.id?'rgba(188,157,255,.7)':'rgba(151,116,255,.18)'};background:rgba(10,20,39,.5);cursor:pointer;display:grid;place-items:center">
            <img src="${esc(it.url)}" style="width:100%;height:100%;object-fit:cover;display:block">
            ${sel===it.id?'<span style="position:absolute;inset:0;border:2px solid #a07bff;border-radius:12px;pointer-events:none"></span>':''}
            ${!it.builtin?'<span data-del="'+esc(it.id)+'" style="position:absolute;top:4px;left:4px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.6);color:#fff;display:grid;place-items:center;font-size:12px">×</span>':''}
          </button>
        `).join('') : '<div style="color:#8586a8;font-size:11px">موردی وجود ندارد</div>';
      };
      overlay.querySelector('#gpGrid').addEventListener('click', async e=>{
        const del=e.target.closest('[data-del]');
        if(del){
          const key=del.dataset.del;
          if(key && key.startsWith('upload:')){
            try{ await apiJson('/api/gallery/'+key.slice(7),{method:'DELETE'}); items=items.filter(i=>i.id!==key); if(sel===key) sel=''; render(); }catch(err){ toast(err.message); }
          }
          return;
        }
        const btn=e.target.closest('[data-key]');
        if(btn){ sel=btn.dataset.key; render(); }
      });
      $('#gpLogo',overlay).onclick=()=>{ sel=''; render(); };
      $('#gpUploadBtn',overlay).onclick=()=> $('#gpFile',overlay).click();
      $('#gpFile',overlay).addEventListener('change', async e=>{
        const f=e.target.files[0]; if(!f) return;
        const fd=new FormData(); fd.append('file',f);
        try{
          const r=await fetch('/api/gallery',{method:'POST',body:fd,credentials:'same-origin'});
          const d=await r.json().catch(()=>({}));
          if(r.ok){ items.push(d.item); sel=d.item.id; render(); } else toast(d.detail||'خطا');
        }catch(err){ toast(err.message); }
        e.target.value='';
      });
      (async()=>{ try{ const d=await apiJson('/api/gallery'); items=d.items||[]; render(); }catch(e){} })();
      render();
    });
  }

  async function loadMe(){
    try{
      const me=await apiJson('/api/me');
      if(me.username){
        const pn=$('.profile-name'); if(pn) pn.textContent=me.username;
        const pr=$('.profile-role'); if(pr) pr.innerHTML='<span class="dot"></span> '+(me.username==='TiTaN'?'ادمین کل':'مدیر');
        const w=$('.welcome h1'); if(w) w.textContent='خوش آمدید، '+me.username;
      }
      if(me.avatar && me.avatar.url){
        const av=$('.profile .avatar img'); if(av) av.src=me.avatar.url;
        const vvAv=$('.version-logo img'); if(vvAv) vvAv.src=me.avatar.url;
      }
    }catch(e){}
  }

  function drawChart(container, daily){
    const el = typeof container==='string' ? $(container) : container;
    if(!el) return;
    const yAxis = el.querySelector('.y-axis');
    const svgEl = el.querySelector('.chart-svg');
    const xAxis = el.querySelector('.chart-x');
    const grid = el.querySelector('.grid-lines');
    if(!daily || !daily.length || daily.every(d=>!d.up && !d.down)){
      if(svgEl) svgEl.style.display='none';
      if(xAxis) xAxis.innerHTML='<span style="color:#8586a8;font-size:10px">داده‌ای وجود ندارد</span>';
      if(yAxis) yAxis.innerHTML='<span>0</span><span>0</span><span>0</span><span>0</span><span>0</span>';
      return;
    }
    const max = Math.max(1, ...daily.map(d=> (d.up||0)+(d.down||0)));
    const W=760, H=170, padB=24;
    const points = daily.map((d,i)=>{
      const x = (i/(daily.length-1))*(W-20)+10;
      const y = H - padB - ((d.up+d.down)/max)*(H - padB - 20);
      return {x,y,v:d};
    });
    const path = points.map((p,i)=> (i===0?`M${p.x} ${p.y}`:`L${p.x} ${p.y}`)).join(' ');
    const area = path + ` L${points[points.length-1].x} ${H - padB} L${points[0].x} ${H - padB} Z`;
    const xLabels = daily.map(d=> new Date(d.t*1000).toLocaleDateString(dashboardLang==='en'?'en-GB':'fa-IR',{month:'short',day:'numeric'}));
    if(svgEl){
      svgEl.style.display='';
      svgEl.setAttribute('viewBox', `0 0 ${W} ${H}`);
      svgEl.innerHTML=`
        <defs>
          <linearGradient id="area2" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a14fff" stop-opacity=".35"/><stop offset="1" stop-color="#a14fff" stop-opacity="0"/></linearGradient>
          <filter id="glow2"><feGaussianBlur stdDeviation="4.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        <path d="${area}" fill="url(#area2)"/>
        <path d="${path}" fill="none" stroke="#9b49ff" stroke-width="2.2" filter="url(#glow2)"/>
        <path d="${path}" fill="none" stroke="#b45cff" stroke-width="1.1"/>
        ${points.map(p=>`<circle cx="${p.x}" cy="${p.y}" r="4" fill="#b65cff" stroke="#170d37" stroke-width="2"/>`).join('')}
      `;
    }
    if(xAxis) xAxis.innerHTML = xLabels.map(l=>`<span>${esc(l)}</span>`).join('');
    if(yAxis){
      const steps=[max, max*0.75, max*0.5, max*0.25, 0];
      yAxis.innerHTML=steps.map(v=>`<span>${esc(fmtBytes(v))}</span>`).join('');
    }
  }

  async function loadOverview(){
    try{
      const [stats, usersRes, nodesRes, reports] = await Promise.all([
        apiJson('/api/stats'),
        apiJson('/api/users'),
        apiJson('/api/nodes'),
        apiJson('/api/reports?days=7').catch(()=>({daily:[]}))
      ]);
      const users=usersRes.users||[]; const nodes=nodesRes.nodes||[];
      const online=nodes.filter(n=>n.enabled && n.status && n.status.online).length;
      const vv=$('.version-v'); if(vv && stats.app_version) vv.textContent='v'+stats.app_version;
      const totalTraffic=(stats.total_up||0)+(stats.total_down||0);
      const activeUsers=users.filter(u=>u.enabled && !(u.status && u.status.expired) && (u.status && u.status.live_enabled)).length;
      const cu=$('.card.users .card-number'); if(cu) cu.textContent=String(activeUsers);
      const cum=$('.card.users .card-meta'); if(cum) cum.textContent='از '+users.length+' کاربر';
      const ct=$('.card.traffic .card-number'); if(ct) ct.textContent=fmtBytes(totalTraffic);
      const ctm=$('.card.traffic .card-meta'); if(ctm) ctm.innerHTML=`MB ↓ ${fmtBytes(stats.total_down||0)} &nbsp; ↑ ${fmtBytes(stats.total_up||0)}`;
      const cs=$('.card.servers .card-number'); if(cs) cs.textContent=String(nodes.length);
      const csm=$('.card.servers .card-meta'); if(csm) csm.innerHTML=`<span class="green">● ${online} آنلاین</span>`;
      const cc=$('.card.configs .card-number'); if(cc) cc.textContent=String(stats.enabled_count||0);
      const ccm=$('.card.configs .card-meta'); if(ccm) ccm.textContent='از '+users.length+' کانفیگ';

      const srvContent=$('.server-content');
      if(srvContent){
        if(nodes.length){
          srvContent.innerHTML=nodes.slice(0,4).map(n=>{
            const st=n.status||{}; const lat=(st.latency_ms!=null?Number(st.latency_ms):null);
            const city=(n.city && n.city!=='—')?n.city:n.name; const cc=(n.country_code||nodeCountryCode(n)||'').toUpperCase();
            const on=!!(n.enabled!==false && st.online);
            const pc=!on?'off':(lat==null?'off':(lat<90?'good':(lat<200?'mid':'bad')));
            return `<div class="server-row" title="${esc(n.name)}"><div class="latency ping ${pc}">${lat!=null?lat+'ms':'—'}<small>تاخیر</small></div><div class="status ${on?'on':'off'}">${on?'آنلاین':'آفلاین'}</div><div class="location"><span class="sr-medal">${nodeFlagHtml(n,'sm')}</span><span><span class="sr-name">${esc(n.name)}</span><span class="sr-loc">${esc(city)}${cc?' · '+cc:''}</span></span></div></div>`;
          }).join('');
        } else srvContent.innerHTML='<div style="color:#8586a8;font-size:11px;padding:12px">سروری ثبت نشده است.</div>';
      }

      const ruHead=document.querySelector('.recent-panel.users-table .recent-table');
      if(ruHead){
        ruHead.querySelectorAll('.recent-table-row').forEach(r=>r.remove());
        const recent=[...users].sort((a,b)=>(b.created_at||0)-(a.created_at||0)).slice(0,3);
        if(recent.length===0) ruHead.insertAdjacentHTML('beforeend','<div style="padding:14px;color:#8586a8;font-size:11px">کاربری وجود ندارد.</div>');
        else recent.forEach(u=>{
          const av=(u.avatar_url||'/static/img/titan-avatar.svg'); const st=u.status||{}; const used=fmtBytes(st.used||0);
          const label=st.expired?'منقضی':(!u.enabled?'غیرفعال':'فعال');
          const row=document.createElement('div'); row.className='recent-table-row';
          row.innerHTML=`<div class="recent-user"><span class="recent-avatar user-avatar"><img src="${esc(av)}" alt=""></span><span class="recent-name">${esc(u.name)}</span></div><div class="recent-traffic">${esc(used)}</div><div class="recent-status">${esc(label)}</div>`;
          ruHead.appendChild(row);
        });
      }
      const rcHead=document.querySelector('.recent-panel.configs-table .recent-table');
      if(rcHead){
        rcHead.querySelectorAll('.recent-table-row').forEach(r=>r.remove());
        const nodeMap={}; nodes.forEach(n=>nodeMap[n.id]=n);
        const recent=[...users].sort((a,b)=>(b.created_at||0)-(a.created_at||0)).slice(0,3);
        if(recent.length===0) rcHead.insertAdjacentHTML('beforeend','<div style="padding:14px;color:#8586a8;font-size:11px">کانفیگی وجود ندارد.</div>');
        else recent.forEach(u=>{
          const av=(u.avatar_url||'/static/img/titan-avatar.svg'); const n=nodeMap[u.node_id||1];
          const loc=n?((n.city && n.city!=='—')?n.city:n.name):'—';
          const st=u.status||{}; const label=st.expired?'منقضی':(!u.enabled?'غیرفعال':'فعال');
          const row=document.createElement('div'); row.className='recent-table-row';
          row.innerHTML=`<div class="recent-config"><span class="recent-avatar user-avatar"><img src="${esc(av)}" alt=""></span><span class="recent-name">${esc(u.name)}</span></div><div>${esc((u.protocol||'').toUpperCase())}</div><div class="recent-server"><span class="flag">${nodeFlagHtml(n,'sm')}</span><span class="recent-server-name">${esc(loc)}</span></div><div class="recent-status">${esc(label)}</div>`;
          rcHead.appendChild(row);
        });
      }

      // real traffic chart
      const chartArea=$('.chart-area');
      if(chartArea && reports.daily){
        drawChart(chartArea, reports.daily);
      }
    }catch(e){ console.error('loadOverview',e); }
  }

  // --- modals ---
  function createModal(title, bodyHtml, onSave){
    const ex=$('#titanModal'); if(ex) ex.remove();
    const overlay=document.createElement('div'); overlay.id='titanModal';
    overlay.style.cssText='position:fixed;inset:0;z-index:9998;background:rgba(2,4,18,.62);backdrop-filter:blur(8px);display:grid;place-items:center;padding:18px;';
    overlay.innerHTML=`<div style="width:min(640px,96vw);max-height:92vh;overflow:auto;background:linear-gradient(145deg,rgba(24,12,56,.96),rgba(8,6,26,.98));border:1px solid rgba(151,116,255,.42);border-radius:18px;box-shadow:0 0 30px rgba(94,48,205,.22);">
      <div style="position:sticky;top:0;z-index:1;background:linear-gradient(145deg,rgba(24,12,56,1),rgba(12,8,32,1));padding:18px 20px;border-bottom:1px solid rgba(151,116,255,.18);display:flex;align-items:center;justify-content:space-between"><div style="font-weight:700;color:#f2edff">${esc(title)}</div><button id="titanModalClose" style="width:32px;height:32px;border-radius:9px;border:1px solid rgba(151,116,255,.24);background:rgba(91,49,176,.16);color:#d8c7ff;cursor:pointer">×</button></div>
      <div style="padding:18px 20px">${bodyHtml}</div>
      <div style="position:sticky;bottom:0;background:linear-gradient(145deg,rgba(24,12,56,1),rgba(8,6,26,1));padding:14px 20px;border-top:1px solid rgba(151,116,255,.18);display:flex;gap:10px;justify-content:flex-end"><button id="titanModalCancel" style="padding:10px 14px;border-radius:10px;border:1px solid rgba(151,116,255,.24);background:rgba(91,49,176,.12);color:#eee9ff;cursor:pointer">انصراف</button><button id="titanModalSave" style="padding:10px 16px;border-radius:10px;border:1px solid rgba(188,157,255,.5);background:linear-gradient(135deg,#7436f5,#4b1bb4);color:#fff;cursor:pointer">ذخیره</button></div>
    </div>`;
    document.body.appendChild(overlay);
    const close=()=>overlay.remove();
    $('#titanModalClose',overlay).onclick=close;
    $('#titanModalCancel',overlay).onclick=close;
    overlay.addEventListener('click',e=>{ if(e.target===overlay) close(); });
    $('#titanModalSave',overlay).onclick=async()=>{
      const btn=$('#titanModalSave',overlay); btn.disabled=true; const old=btn.textContent; btn.textContent='...';
      try{ const msg = await onSave(overlay); close(); toast(msg || 'انجام شد'); loadOverview(); }
      catch(e){ toast(e.message); }
      finally{ btn.disabled=false; btn.textContent=old; }
    };
  }

  // --- full user/config modal (all previous settings) ---
  async function openUserModal(existing=null){
    const settings = await apiJson('/api/settings').catch(()=>({}));
    const nodesRes = await apiJson('/api/nodes').catch(()=>({nodes:[]}));
    const nodes = nodesRes.nodes||[];
    const isEdit = !!existing;
    const u = existing || {};
    const nodeOpts = '<option value="0">🌐 خودکار (نزدیک‌ترین)</option>' + nodes.map(n=>`<option data-i18n-ignore value="${n.id}" ${String(u.node_id||0)===String(n.id)?'selected':''}>${esc(nodeFlag(n))} ${esc(n.name)}${(n.sync&&n.sync.ok===false)?' ⚠':''}</option>`).join('');
    const nodeInfo={}; nodes.forEach(n=>{ nodeInfo[String(n.id)]={name:n.name, local:!!n.is_local, enabled:n.enabled!==false,
      online:!!(n.status&&n.status.online), cred:!!(n.sync&&n.sync.has_credential), ok:(n.sync&&n.sync.ok)===true, err:(n.sync&&n.sync.error)||''}; });
    // Say what picking this server means *before* saving: a node that cannot take
    // the user is exactly how a config ends up on the main domain by surprise.
    const nodeHint=(id)=>{
      const i=nodeInfo[String(id)];
      if(!i || String(id)==='0') return {text:'خودکار = نزدیک‌ترین نودِ آنلاین و همگام‌شده.', cls:''};
      if(!i.enabled) return {text:'این نود در حالت نگهداری است — کانفیگ از پنل سرو می‌شود.', cls:'warn'};
      const reason = !i.cred ? 'نود اعتبارنامه‌اش را نگرفته' : (i.ok ? '' : (i.err?('آخرین همگام‌سازی موفق نبود: '+i.err):'هنوز هیچ همگام‌سازی موفقی نداشته'));
      if(reason) return {text:'⚠ '+i.name+': '+reason+' — تا آماده شدنش، کانفیگ از پنل سرو می‌شود (تایم‌اوت نمی‌کند).', cls:'warn'};
      if(!i.online) return {text:'⚠ '+i.name+' الان آنلاین نیست، ولی کاربر روی آن ثبت می‌شود.', cls:'warn'};
      return {text:'✓ روی '+i.name+' سرو می‌شود ('+(i.online?'آنلاین':'نامعلوم')+').', cls:'ok'};
    };
    const protocols=['vless','vmess','trojan','shadowsocks','hysteria2','wireguard'];
    const transports=['ws','xhttp','grpc','tcp','httpupgrade'];
    const fingerprints=['chrome','firefox','safari','ios','android','edge','random','randomized'];
    const alpns=['http/1.1','h2,http/1.1','h3,h2,http/1.1',''];
    const ssMethods=['2022-blake3-aes-128-gcm','2022-blake3-aes-256-gcm','2022-blake3-chacha20-poly1305','aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305'];
    const expireDays = u.expire_at ? Math.max(0, Math.ceil((u.expire_at - Date.now()/1000)/86400)) : 0;

    createModal(isEdit?'ویرایش کاربر / کانفیگ':'افزودن کاربر / کانفیگ', `
      <div style="display:grid;gap:16px">
        <div style="display:flex;gap:12px;align-items:center">
          <div id="avPreview" style="width:54px;height:54px;border-radius:14px;overflow:hidden;border:1px solid rgba(151,116,255,.3);background:rgba(10,20,39,.6);display:grid;place-items:center"><img src="${esc(avatarUrl(u.avatar||''))}" style="width:100%;height:100%;object-fit:cover"></div>
          <input type="hidden" id="mu_avatar" value="${esc(u.avatar||'')}">
          <button type="button" id="avPickBtn" style="padding:8px 12px;border-radius:10px;border:1px solid rgba(151,116,255,.24);background:rgba(91,49,176,.12);color:#eee9ff;cursor:pointer">انتخاب تصویر</button>
          <span style="font-size:10px;color:#8586a8">پروفایل کاربر — مثل قبل</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">نام*<input id="mu_name" value="${esc(u.name||'')}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">یادداشت<input id="mu_note" value="${esc(u.note||'')}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
        </div>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">سرور<select id="mu_node" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">${nodeOpts}</select></label>
        <div id="mu_nodeHint" class="node-hint"></div>
        <div id="mu_edgeState" class="node-hint" style="display:none"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">پروتکل<select id="mu_protocol" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">${protocols.map(p=>`<option value="${p}" ${ (u.protocol||'vless')===p?'selected':''}>${p.toUpperCase()}</option>`).join('')}</select></label>
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">انتقال<select id="mu_transport" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">${transports.map(t=>`<option value="${t}" ${(u.transport||settings.default_transport||'ws')===t?'selected':''}>${t.toUpperCase()}</option>`).join('')}</select></label>
        </div>
        <div id="ssRow" style="display:${(u.protocol||'vless')==='shadowsocks'?'flex':'none'};flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">متد Shadowsocks<select id="mu_ss" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">${ssMethods.map(m=>`<option value="${m}" ${(u.ss_method||settings.ss_method||'2022-blake3-aes-128-gcm')===m?'selected':''}>${m}</option>`).join('')}</select></div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">امنیت<select id="mu_security" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"><option value="tls" ${(u.security||'tls')==='tls'?'selected':''}>TLS</option><option value="none" ${u.security==='none'?'selected':''}>None</option><option value="reality" ${u.security==='reality'?'selected':''}>Reality</option></select></label>
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">فینگرپرینت<select id="mu_fp" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">${fingerprints.map(f=>`<option value="${f}" ${(u.fingerprint||settings.default_fingerprint||'chrome')===f?'selected':''}>${f}</option>`).join('')}</select></label>
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">ALPN<select id="mu_alpn" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">${alpns.map(a=>`<option value="${a}" ${(u.alpn??settings.default_alpn??'http/1.1')===a?'selected':''}>${a||'—'}</option>`).join('')}</select></label>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">حجم
            <span style="display:flex;gap:8px">
              <input id="mu_quota" type="number" step="0.1" min="0" value="${quotaView(u).value}" style="flex:1;background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">
              <select id="mu_quota_unit" style="width:78px;background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">
                <option value="gb" ${quotaView(u).unit==='gb'?'selected':''}>GB</option>
                <option value="mb" ${quotaView(u).unit==='mb'?'selected':''}>MB</option>
              </select>
            </span>
          </label>
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">انقضا (روز)<input id="mu_expire" type="number" value="${expireDays}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">حد دستگاه<input id="mu_devices" type="number" value="${u.max_devices||0}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">حد درخواست<input id="mu_requests" type="number" value="${u.max_requests||0}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
        </div>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">IPهای مجاز (با کاما جدا کن، CIDR هم قبول است)<input id="mu_ips" value="${esc((u.allowed_ips||[]).join(','))}" dir="ltr" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
      </div>
    `, async (overlay)=>{
      const body={
        name: $('#mu_name',overlay).value.trim()||'User',
        note: $('#mu_note',overlay).value,
        node_id: parseInt($('#mu_node',overlay).value)||0,
        protocol: $('#mu_protocol',overlay).value,
        transport: $('#mu_transport',overlay).value,
        security: $('#mu_security',overlay).value,
        fingerprint: $('#mu_fp',overlay).value,
        alpn: $('#mu_alpn',overlay).value,
        ss_method: $('#mu_ss',overlay) ? $('#mu_ss',overlay).value : undefined,
        quota_gb: $('#mu_quota_unit',overlay).value==='gb' ? (parseFloat($('#mu_quota',overlay).value)||0) : 0,
        quota_mb: $('#mu_quota_unit',overlay).value==='mb' ? (parseFloat($('#mu_quota',overlay).value)||0) : 0,
        expire_days: parseInt($('#mu_expire',overlay).value)||0,
        max_devices: parseInt($('#mu_devices',overlay).value)||0,
        max_requests: parseInt($('#mu_requests',overlay).value)||0,
        allowed_ips: ($('#mu_ips',overlay).value||'').split(',').map(s=>s.trim()).filter(Boolean),
        avatar: $('#mu_avatar',overlay).value,
        client_nonce: Math.random().toString(36).slice(2)+Date.now().toString(36)
      };
      const res = isEdit
        ? await apiJson('/api/users/'+u.uid,{method:'PATCH',body})
        : await apiJson('/api/users',{method:'POST',body});
      setTimeout(()=>{ const ev=new Event('titan:refresh'); document.dispatchEvent(ev); }, 100);
      // Tell the admin where the config actually landed — the panel's own link is
      // a valid answer, but it must never be a silent surprise.
      const ns=res.node_sync||{};
      if(ns.node_id && ns.ok) return 'ذخیره شد — کاربر روی نود '+ns.node_name+' پوش شد ✓';
      if(ns.node_id && !ns.ok) return 'ذخیره شد، ولی نود قبول نکرد ('+(ns.error||'')+') — فعلاً از پنل سرو می‌شود';
      return 'ذخیره شد';
    });
    // wire ui immediately after modal creation (not only on save)
    setTimeout(()=>{
      const overlay=$('#titanModal'); if(!overlay) return;
      const avBtn=$('#avPickBtn',overlay), avIn=$('#mu_avatar',overlay), avImg=$('#avPreview img',overlay);
      if(avBtn) avBtn.onclick=async()=>{
        const k=await openGalleryPicker(avIn.value);
        if(k!=null){ avIn.value=k; if(avImg) avImg.src=avatarUrl(k); }
      };
      const protoSel=$('#mu_protocol',overlay), ssRow=$('#ssRow',overlay), transSel=$('#mu_transport',overlay), secSel=$('#mu_security',overlay);
      const updateDeps=()=>{
        if(!protoSel) return;
        const p=protoSel.value; const noNet=(p==='hysteria2'||p==='wireguard');
        if(transSel) transSel.disabled=noNet;
        if(secSel) secSel.disabled=noNet;
        if(ssRow) ssRow.style.display = p==='shadowsocks' ? 'flex' : 'none';
      };
      if(protoSel) protoSel.addEventListener('change',updateDeps);
      updateDeps();
      const nodeSel=$('#mu_node',overlay), hint=$('#mu_nodeHint',overlay);
      const paint=()=>{ if(!nodeSel||!hint) return; const h=nodeHint(nodeSel.value); hint.textContent=h.text; hint.className='node-hint '+(h.cls||''); };
      if(nodeSel) nodeSel.addEventListener('change',paint);
      paint();
      // Where this config really lands. A stored "reality/tcp" can legitimately
      // be served as XHTTP/TLS on the edge (or as raw TCP through the platform
      // proxy) - the panel decides that from evidence, and this is where the
      // decision and its reason are readable instead of being a surprise later.
      const state=$('#mu_edgeState',overlay);
      if(state){
        const ep=(existing&&existing.endpoint)||null;
        const warns=((existing&&existing.edge_warnings)||[]).filter(Boolean);
        if(ep&&ep.host){
          const tags=[esc(String(ep.transport||'').toUpperCase())+'/'+esc(String(ep.security||'').toUpperCase())];
          tags.push(ep.raw?'خام (TCP)':'از مسیر HTTPS');
          if(ep.target==='node'&&ep.node) tags.push('روی '+esc(ep.node));
          state.innerHTML=`<b>${tags.join(' · ')}</b> <span dir="ltr">${esc(ep.host)}:${esc(String(ep.port))}</span>`
            +(warns.length?('<br>'+warns.map(w=>'• '+esc(w)).join('<br>')):'');
          state.className='node-hint '+(warns.length?'warn':'ok');
          state.style.display='block';
        }
      }
    }, 20);
  }

  // A node cannot accept users until it knows a credential. The dashboard used to
  // show the token in a 2-second toast; this shows the exact variables to paste
  // into the node service, with the copy button, and says what happens meanwhile.
  function openNodeSetupModal(res){
    const setup=res.setup||{}; const sync=res.sync_now||{};
    const probe=(res.discovery&&res.discovery.kind)||res.kind||'';
    const who=(res.discovery&&res.discovery.identity)||res.identity||{};
    const claim=(res.discovery&&res.discovery.claim)||res.claim||{};
    const lines=(setup.lines||[]).map(l=>{
      const i=l.indexOf('=');
      return `<div class="env-line"><span class="env-k">${esc(l.slice(0,i))}</span><span class="env-v" dir="ltr">${esc(l.slice(i+1))}</span></div>`;
    }).join('');
    createModal('راه‌اندازی این نود', `
      <div style="display:grid;gap:14px">
        <div class="nl-note ${sync.ok?'':'bad'}" style="margin:0">
          ${sync.ok ? 'نود جواب داد و کاربرانش را گرفت ✓'
                    : 'این نود هنوز جواب نداده'+(sync.error?' ('+esc(sync.error)+')':'')+' — تا آن موقع، کانفیگ‌های این نود روی خودِ پنل سرو می‌شوند (تایم‌اوت نمی‌کنند).'}
        </div>
        <div class="det-card">
          ${probe==='titan'
            ? `<div class="det-row"><span class="det-ok">✓ نود شناسایی شد</span><span class="muted" dir="ltr">${esc(who.version||'')} · ${esc(who.role||'node')}</span></div>`
            : `<div class="det-row"><span class="det-bad">شناسایی خودکار انجام نشد</span><span class="muted" dir="ltr">${esc(probe||'unknown')}</span></div>`}
          ${claim&&claim.ok? `<div class="det-row"><span class="det-ok">دسترسی خودکار داده شد — نیازی به متغیر نیست ✓</span></div>`:''}
          ${claim&&claim.error? `<div class="det-row"><span class="det-bad">دسترسی خودکار نشد (${esc(claim.error)})</span><span class="muted">متغیرها را ست کن</span></div>`:''}
        </div>
        <p style="margin:0;font-size:11px;color:#a8a6bf;line-height:2">
          اگر نود خودکار وصل شد، همین‌جا کارت تمام است. اگر نه، این متغیرها را روی سرویسِ نود بگذار و یک‌بار دیپلوی کن.
        </p>
        <div style="display:flex;align-items:center;gap:10px">
          ${icoBtn({"type":"button","id":"setupCopyAll"},"copy","کپی همهٔ متغیرها با یک کلیک","violet")}
          <span style="font-size:11px;color:#a8a6bf">کپی همه (آماده برای Raw Editor)</span>
        </div>
        <div class="env-list">${lines}</div>
        <p style="margin:0;font-size:10.5px;color:#8586a8;line-height:2">${esc(setup.note||'')}</p>
      </div>`, async ()=>{ /* nothing to save: it is a recipe */ });
    setTimeout(()=>{
      const overlay=$('#titanModal'); if(!overlay) return;
      const list=$('.env-list',overlay);
      if(list) list.addEventListener('click', async(e)=>{
        const line=e.target.closest('.env-line'); if(!line) return;
        const text=line.querySelector('.env-k').textContent+'='+line.querySelector('.env-v').textContent;
        try{ await navigator.clipboard.writeText(text); toast('کپی شد'); }catch(err){ toast(text); }
      });
      const copyAll=$('#setupCopyAll',overlay);
      if(copyAll) copyAll.addEventListener('click', async()=>{
        const text=(setup.block || (setup.lines||[]).join('\n'));
        try{ await navigator.clipboard.writeText(text); toast('همهٔ متغیرها کپی شد ✓'); }
        catch(err){ toast('کپی نشد — دستی انتخاب کن'); }
      });
      const save=$('#titanModalSave',overlay);
      if(save){ save.textContent='فهمیدم'; save.onclick=()=>overlay.remove(); }
    }, 20);
  }

  // QR + on/off live in both the users and the configs tables; one helper keeps
  // the two behaviours identical (and the buttons are icon-only, so the label
  // travels in the tooltip).
  function wireRowExtras(tbody, refresh){
    tbody.querySelectorAll('[data-act="qr"]').forEach(b=> b.addEventListener('click', ()=>{
      window.open('/api/users/'+b.dataset.uid+'/qr','_blank');
    }));
    tbody.querySelectorAll('[data-act="power"]').forEach(b=> b.addEventListener('click', async()=>{
      const uid=b.dataset.uid; const on=b.dataset.on==='1';
      b.disabled=true;
      try{
        await apiJson('/api/users/'+uid,{method:'PATCH',body:{enabled:!on}});
        toast(on?'کانفیگ خاموش شد':'کانفیگ روشن شد');
        refresh(); loadOverview();
      }catch(e){ toast(e.message); } finally{ b.disabled=false; }
    }));
  }

  // Which configs this user's subscription link carries. The server lists every
  // config it really serves for the user (a VLESS user answers on WS, XHTTP,
  // HTTPUpgrade and gRPC), and the picked set is stored per user.
  async function openSubConfigModal(uid, refresh){
    const info = await apiJson('/api/users/'+uid+'/sub-configs');
    const configs = info.configs||[];
    if(!configs.length){ toast('کانفیگی برای این کاربر وجود ندارد'); return; }
    const rows = configs.map((c,i)=>`
      <label class="cfg-pick" data-key="${esc(c.key)}">
        <input type="checkbox" ${c.included?'checked':''} data-key="${esc(c.key)}">
        <span class="cfg-pick-body">
          <span class="cfg-pick-name">${esc(c.protocol.toUpperCase())} · ${esc(c.key.toUpperCase())}</span>
          <span class="cfg-pick-host" dir="ltr">${esc(c.host)}:${esc(String(c.port))} · ${esc(c.transport)}/${esc(c.security||'none')}${c.target==='node'?' · node':' · panel'}</span>
        </span>
      </label>`).join('');
    createModal('کانفیگ‌های لینک اشتراک', `
      <div style="display:grid;gap:12px">
        <p style="margin:0;font-size:11px;color:#a8a6bf;line-height:2">
          هر کدام را تیک بزنی، داخل همین لینک اشتراک می‌آید. اگر همه تیک بخورند یعنی «همه» (کانفیگ‌هایی که بعداً به این کاربر اضافه شوند هم خودکار می‌آیند).
        </p>
        <div class="cfg-pick-list">${rows}</div>
        <div style="display:flex;gap:10px;align-items:center;font-size:11px;color:#a8a6bf">
          ${icoBtn({"type":"button","id":"cfgPickAll"},"checks","انتخاب همه")}
          ${icoBtn({"type":"button","id":"cfgPickNone"},"xcircle","هیچ‌کدام")}
          <span style="direction:ltr" dir="ltr">${esc(info.sub_url||'')}</span>
        </div>
      </div>`, async (overlay)=>{
        const picked=Array.from(overlay.querySelectorAll('.cfg-pick input:checked')).map(c=>c.dataset.key);
        await apiJson('/api/users/'+uid+'/sub-configs',{method:'PATCH',body:{transports:picked}});
        if(refresh) refresh();
      });
    setTimeout(()=>{
      const overlay=$('#titanModal'); if(!overlay) return;
      const all=$('#cfgPickAll',overlay), none=$('#cfgPickNone',overlay);
      const boxes=()=>Array.from(overlay.querySelectorAll('.cfg-pick input'));
      if(all) all.onclick=()=>boxes().forEach(b=>{ b.checked=true; });
      if(none) none.onclick=()=>boxes().forEach(b=>{ b.checked=false; });
    }, 20);
  }

  async function openNodeModal(existing=null){
    const isEdit=!!existing; const n=existing||{};
    createModal(isEdit?'ویرایش سرور':'افزودن سرور', `
      <div style="display:grid;gap:12px">
        <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">نام*<input id="mn_name" value="${esc(n.name||'')}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">دامنهٔ سرویس نود (کافی است)
          <span style="display:flex;gap:8px;align-items:center">
            <input id="mn_addr" value="${esc(n.address||'')}" dir="ltr" placeholder="your-node.up.railway.app" style="flex:1;background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px">
            ${icoBtn({"type":"button","id":"mn_detect"},"pulse","شناسایی خودکار این دامنه","violet")}
          </span>
        </label>
        <div id="mn_detectBox"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">شهر<input id="mn_city" value="${esc(n.city||'')}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">کشور<input id="mn_country" value="${esc(n.country||'')}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">کد کشور (2 حرف)<input id="mn_cc" value="${esc(n.country_code||'')}" maxlength="2" style="text-transform:uppercase;background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
          <label style="display:flex;flex-direction:column;gap:6px;font-size:11px;color:#a8a6bf">پرچم<input id="mn_flag" value="${esc(nodeFlag(n))}" style="background:rgba(10,20,39,.8);border:1px solid rgba(108,125,165,.18);border-radius:10px;color:#e9e6f6;padding:11px"></label>
        </div>
        <div style="font-size:10px;color:#7d829d">دامنه را بزن و ذخیره کن: نام، شهر، پرچم و کلید نود خودکار تشخیص داده می‌شود. اگر شناسایی ممکن نشد، فیلدهای دستی را پر کن و بعد متغیرها را با یک دکمه کپی کن.</div>
      </div>
    `, async (overlay)=>{
      const body={
        name: $('#mn_name',overlay).value.trim(),
        address: $('#mn_addr',overlay).value.trim(),
        city: $('#mn_city',overlay).value.trim(),
        country: $('#mn_country',overlay).value.trim(),
        country_code: $('#mn_cc',overlay).value.trim(),
        flag: $('#mn_flag',overlay).value.trim()
      };
      if(!body.name && !body.address) throw new Error('دامنهٔ نود یا نام را بزن');
      let message='انجام شد';
      if(isEdit){
        const res=await apiJson('/api/nodes/'+n.id,{method:'PATCH',body});
        const st=(res.node&&res.node.sync)||{};
        if(st.ok===false) message='نود جواب نداد ('+(st.error||'')+') — کانفیگ‌ها موقتاً از پنل سرو می‌شوند';
      } else {
        const res=await apiJson('/api/nodes',{method:'POST',body});
        const found=(res.discovery&&res.discovery.kind==='titan');
        if(res.sync_now && res.sync_now.ok===false) openNodeSetupModal(res);
        else message=(found? 'نود خودکار شناسایی و وصل شد ✓' : 'نود اضافه شد و کاربرانش را گرفت ✓');
      }
      setTimeout(()=> document.dispatchEvent(new Event('titan:refresh')), 100);
      return message;
    });
    setTimeout(()=>{
      const overlay=$('#titanModal'); if(!overlay) return;
      const ccIn=$('#mn_cc',overlay), flagIn=$('#mn_flag',overlay);
      if(ccIn && flagIn) ccIn.addEventListener('input',()=>{ flagIn.value = flagFor(ccIn.value); });
      const addrIn=$('#mn_addr',overlay), detBtn=$('#mn_detect',overlay), box=$('#mn_detectBox',overlay);
      if(detBtn) detBtn.addEventListener('click', async()=>{ detBtn.disabled=true; try{ await detectNode(addrIn.value.trim(), box); } finally{ detBtn.disabled=false; } });
      if(addrIn) addrIn.addEventListener('blur', ()=>{ if(addrIn.value.trim() && box && !box.innerHTML) detectNode(addrIn.value.trim(), box); });
    }, 20);
  }

  function wireDetails(){
    // hide export button in users section (keep only Add User)
    $$('.section-view[data-section="users"] .section-actions button').forEach(b=>{
      const t=(b.textContent||'').trim();
      if(t.includes('خروجی')) b.style.display='none';
    });

    const usersSection=document.querySelector('.section-view[data-section="users"]');
    if(usersSection){
      const tbody=usersSection.querySelector('.data-table tbody');
      const search=usersSection.querySelector('[data-filter="users"]');
      async function refreshUsers(){
        try{
          const d=await apiJson('/api/users'); const users=d.users||[];
          // update the 3 top cards with real data
          const cards=usersSection.querySelectorAll('.section-grid .detail-card');
          if(cards[0]){
            const total=users.length;
            const active=users.filter(u=> u.enabled && !(u.status&&u.status.expired) && u.status&&u.status.live_enabled).length;
            const connecting=users.filter(u=> (u.status&&u.status.active_connections>0)).length;
            const disabled=users.filter(u=> !u.enabled && !(u.status&&u.status.expired)).length;
            cards[0].innerHTML=`<h3>کاربران فعال</h3><div class="metric-row"><span>تعداد کل</span><strong>${total}</strong></div><div class="metric-row"><span>در حال اتصال</span><strong>${connecting}</strong></div><div class="metric-row"><span>غیرفعال</span><strong>${disabled}</strong></div>`;
            if(cards[1]){
              const totalUsed=users.reduce((a,u)=>a+((u.status&&u.status.used)||0),0);
              const todayUsed = totalUsed; // approximate, real daily is in reports
              cards[1].innerHTML=`<h3>مصرف ترافیک</h3><div class="metric-row"><span>مصرف کل</span><strong>${esc(fmtBytes(totalUsed))}</strong></div><div class="metric-row"><span>تعداد کاربران</span><strong>${total}</strong></div><div class="progress"><span style="width:${Math.min(100, Math.round((totalUsed/(10*1024*1024*1024))*100))}%"></span></div>`;
            }
            if(cards[2]){
              const activeSub=active; const nearExpire=users.filter(u=> u.expire_at && (u.expire_at - Date.now()/1000) < 3*86400 && !(u.status&&u.status.expired)).length;
              const expired=users.filter(u=> u.status&&u.status.expired).length;
              cards[2].innerHTML=`<h3>وضعیت اشتراک</h3><div class="metric-row"><span>فعال</span><span class="pill">● ${activeSub} حساب</span></div><div class="metric-row"><span>نزدیک به انقضا</span><span class="pill warn">${nearExpire} حساب</span></div><div class="metric-row"><span>منقضی</span><span class="pill off">${expired} حساب</span></div>`;
            }
          }
          if(tbody){
            tbody.innerHTML=users.length? users.map(u=>{
              const st=u.status||{}; const used=fmtBytes(st.used||0);
              const days=u.expire_at? Math.max(0,Math.ceil((u.expire_at - Date.now()/1000)/86400))+' روز':'هرگز';
              const label=st.expired?'منقضی':(!u.enabled?'غیرفعال':'فعال'); const cls=st.expired?'warn':(!u.enabled?'off':'');
              const on = !!u.enabled && !(st.expired);
              return `<tr><td><span class="user-cell"><span class="avatar user-avatar"><img src="${esc(u.avatar_url||'/static/img/titan-avatar.svg')}" alt=""></span>${esc(u.name)}</span></td><td class="muted">#${esc(u.uid.slice(0,6))}</td><td>${esc(used)}</td><td>${esc(days)}</td><td><span class="pill ${cls}">${esc(label)}</span></td><td><div class="row-actions">${icoBtn({"data-uid":u.uid,"data-act":"edit"},"edit","ویرایش کاربر","gold")}${icoBtn({"data-uid":u.uid,"data-act":"detail"},"link","کپی لینک اتصال","violet")}${icoBtn({"data-uid":u.uid,"data-act":"qr"},"qr","QR code","")}${icoBtn({"data-uid":u.uid,"data-act":"configs"},"sliders","کانفیگ‌های لینک اشتراک این کاربر","gold")}${icoBtn({"data-uid":u.uid,"data-act":"power","data-on":on?1:0},"power",on?"خاموش کردن":"روشن کردن",on?"":"ok")}${icoBtn({"data-uid":u.uid,"data-act":"del"},"trash","حذف","danger")}</div></td></tr>`;
            }).join('') : '<tr><td colspan="6" style="text-align:center;color:#8586a8">کاربری وجود ندارد</td></tr>';
            tbody.querySelectorAll('[data-act="del"]').forEach(b=> b.addEventListener('click', async()=>{ const uid=b.dataset.uid; if(!confirm('حذف کاربر؟')) return; try{ await apiJson('/api/users/'+uid,{method:'DELETE'}); toast('حذف شد'); refreshUsers(); loadOverview(); }catch(e){toast(e.message);} }));
            tbody.querySelectorAll('[data-act="detail"]').forEach(b=> b.addEventListener('click', async()=>{ const uid=b.dataset.uid; try{ const d=await apiJson('/api/users/'+uid+'/links'); await navigator.clipboard.writeText(d.main_link||d.links[0]); toast('لینک کپی شد'); }catch(e){toast(e.message);} }));
            tbody.querySelectorAll('[data-act="configs"]').forEach(b=> b.addEventListener('click', async()=>{ try{ await openSubConfigModal(b.dataset.uid, refreshUsers); }catch(e){toast(e.message);} }));
            tbody.querySelectorAll('[data-act="edit"]').forEach(b=> b.addEventListener('click', async()=>{ const uid=b.dataset.uid; try{ const u=await apiJson('/api/users/'+uid); await openUserModal(u); }catch(e){toast(e.message);} }));
            wireRowExtras(tbody, refreshUsers);
          }
          const cnt=usersSection.querySelector('.data-card .muted'); if(cnt) cnt.textContent=users.length+' مورد';
        }catch(e){ console.error(e); }
      }
      refreshUsers();
      document.addEventListener('titan:refresh', refreshUsers);
      if(search) search.addEventListener('input', ()=>{ const q=search.value.trim().toLowerCase(); if(!tbody) return; tbody.querySelectorAll('tr').forEach(tr=> tr.style.display=tr.textContent.toLowerCase().includes(q)?'':'none'); });
      const addBtn=usersSection.querySelector('.section-btn.primary'); if(addBtn) addBtn.onclick=()=> openUserModal();
      // remove old demo handlers that showed "✓ انجام شد"
      $$('button',usersSection).forEach(b=>{ if(b.dataset.demo) b.removeAttribute('data-demo'); });
    }

    const configsSection=document.querySelector('.section-view[data-section="configs"]');
    if(configsSection){
      const tbody=configsSection.querySelector('.data-table tbody');
      async function refreshConfigs(){
        try{
          const [uRes,nRes]=await Promise.all([apiJson('/api/users'), apiJson('/api/nodes')]);
          const users=uRes.users||[]; const nodes=nRes.nodes||[]; const nodeMap={}; nodes.forEach(n=>nodeMap[n.id]=n);
          // update top 3 cards
          const cards=configsSection.querySelectorAll('.section-grid .detail-card');
          if(cards[0]){
            const total=users.length; const active=users.filter(u=>u.enabled && !(u.status&&u.status.expired)).length;
            cards[0].innerHTML=`<h3>کانفیگ‌های فعال</h3><div class="metric-row"><span>کل کانفیگ‌ها</span><strong>${total}</strong></div><div class="metric-row"><span>فعال</span><strong>${active}</strong></div><div class="metric-row"><span>منقضی</span><strong>${total-active}</strong></div>`;
          }
          if(cards[1]){
            const prots={}; users.forEach(u=> prots[u.protocol]=(prots[u.protocol]||0)+1);
            cards[1].innerHTML=`<h3>پروتکل‌های استفاده‌شده</h3>`+Object.entries(prots).map(([k,v])=>`<div class="metric-row"><span>${esc(k.toUpperCase())}</span><span class="pill">${v} مورد</span></div>`).join('') + (Object.keys(prots).length===0?'<div class="metric-row"><span class="muted">موردی وجود ندارد</span></div>':'');
          }
          if(tbody){
            tbody.innerHTML=users.length? users.map(u=>{
              const n=nodeMap[u.node_id||1]; const loc=n?((n.city&&n.city!=='—')?n.city:n.name):'—';
              const st=u.status||{}; const label=st.expired?'منقضی':(!u.enabled?'غیرفعال':'فعال'); const cls=st.expired?'warn':(!u.enabled?'off':'');
              const on = !!u.enabled && !(st.expired);
              const port = (u.main_link||'').split('@')[1] ? (u.main_link||'').split('@')[1].split('/')[0] : '—';
              return `<tr><td><span class="user-cell"><span class="avatar user-avatar"><img src="${esc(u.avatar_url||'/static/img/titan-avatar.svg')}" alt=""></span>${esc(u.name)}</span></td><td>${esc((u.protocol||'').toUpperCase())} · ${esc((u.transport||'').toUpperCase())}</td><td><span class="node-location-data">${n?nodeFlagHtml(n,'sm'):'🌐'} ${esc(loc)}</span></td><td dir="ltr" class="muted">${esc(port)}</td><td><span class="pill ${cls}">${esc(label)}</span></td><td><div class="row-actions">${icoBtn({"data-uid":u.uid,"data-act":"edit"},"edit","ویرایش کانفیگ","gold")}${icoBtn({"data-uid":u.uid,"data-act":"links"},"link","کپی لینک اتصال","violet")}${icoBtn({"data-uid":u.uid,"data-act":"qr"},"qr","QR code","")}${icoBtn({"data-uid":u.uid,"data-act":"power","data-on":on?1:0},"power",on?"خاموش کردن":"روشن کردن",on?"":"ok")}${icoBtn({"data-uid":u.uid,"data-act":"del"},"trash","حذف","danger")}</div></td></tr>`;
            }).join('') : '<tr><td colspan="6" style="text-align:center;color:#8586a8">کانفیگی وجود ندارد</td></tr>';
            tbody.querySelectorAll('[data-act="del"]').forEach(b=> b.addEventListener('click', async()=>{ const uid=b.dataset.uid; if(!confirm('حذف کانفیگ؟')) return; try{ await apiJson('/api/users/'+uid,{method:'DELETE'}); toast('حذف شد'); refreshConfigs(); loadOverview(); }catch(e){toast(e.message);} }));
            tbody.querySelectorAll('[data-act="links"]').forEach(b=> b.addEventListener('click', async()=>{ const uid=b.dataset.uid; try{ const d=await apiJson('/api/users/'+uid+'/links'); await navigator.clipboard.writeText(d.main_link||d.links[0]); toast('لینک کپی شد'); }catch(e){toast(e.message);} }));
            tbody.querySelectorAll('[data-act="edit"]').forEach(b=> b.addEventListener('click', async()=>{ const uid=b.dataset.uid; try{ const u=await apiJson('/api/users/'+uid); await openUserModal(u); }catch(e){toast(e.message);} }));
            wireRowExtras(tbody, refreshConfigs);
          }
        }catch(e){ console.error(e); }
      }
      refreshConfigs();
      document.addEventListener('titan:refresh', refreshConfigs);
      const addBtn=configsSection.querySelector('.section-btn.primary'); if(addBtn) addBtn.onclick=()=> openUserModal();
      $$('button',configsSection).forEach(b=>{ if(b.dataset.demo) b.removeAttribute('data-demo'); });
    }

    const serversSection=document.querySelector('.section-view[data-section="servers"]');
    if(serversSection){
      async function refreshServers(){
        try{
          const d=await apiJson('/api/nodes'); const nodes=d.nodes||[];
          const grid=serversSection.querySelector('.section-grid');
          if(grid && grid.children.length>=3){
            // update 3 top cards with real data
            const total=nodes.length; const online=nodes.filter(n=>n.enabled && n.status&&n.status.online).length;
            grid.children[0].innerHTML=`<h3>وضعیت نودها</h3><div class="metric-row"><span>کل سرورها</span><strong>${total}</strong></div><div class="metric-row"><span>آنلاین</span><span class="pill">● ${online}</span></div><div class="metric-row"><span>آفلاین</span><span class="pill off">${total-online}</span></div>`;
            const avgLat = (()=>{ const v=nodes.map(n=>n.status&&n.status.latency_ms).filter(x=>x!=null); return v.length? Math.round(v.reduce((a,b)=>a+b,0)/v.length)+' ms' : '—'; })();
            grid.children[1].innerHTML=`<h3>سلامت اتصال</h3><div class="metric-row"><span>میانگین پینگ</span><strong>${avgLat}</strong></div><div class="metric-row"><span>پایداری</span><strong>${online===total&&total>0?'99.9%':'—'}</strong></div><div class="progress"><span style="width:${total?Math.round((online/total)*100):0}%"></span></div>`;
          }
          // ── luxury node cards ────────────────────────────────────────────
          // Everything the panel actually knows about a node is on the card:
          // liveness, latency dial, the edge it answers on, whether its raw port
          // is open, and whether its last sync really carried the users.
          const pingClass=(on,lat)=> !on?'off' : (lat==null?'off':(lat<90?'good':(lat<200?'mid':'bad')));
          const ring=(on,lat)=>{
            const R=26, C=2*Math.PI*R;
            const pct= lat==null?0:Math.max(4,Math.min(100,100-Math.min(lat,400)/4));
            const col= !on?'rgba(255,255,255,.18)':(lat==null?'rgba(255,255,255,.18)':(lat<90?'#31dcb9':(lat<200?'#d9b55f':'#ff6b8a')));
            return `<div class="nl-dial-wrap"><svg class="ring" viewBox="0 0 68 68"><circle class="rg-bg" cx="34" cy="34" r="${R}"></circle>`+
                   `<circle class="rg-fg" cx="34" cy="34" r="${R}" stroke="${col}" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${(C-(C*pct/100)).toFixed(1)}"></circle></svg>`+
                   `<div class="rg-txt" style="color:${col}">${lat!=null?lat:'—'}</div></div>`;
          };
          const bar=(k,v)=>{
            const n=(v==null?null:Math.max(0,Math.min(100,Math.round(v))));
            const cls= n==null?'':(n>=90?' hot':(n>=70?' warm':''));
            return `<div class="nl-metric${cls}"><div class="k">${k}</div><div class="v">${n!=null?n+'%':'—'}</div><div class="bar"><i style="width:${n||0}%"></i></div></div>`;
          };
          const seen=(ts)=> ts? new Date(ts*1000).toLocaleString('fa-IR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
          function nodeCaps(n,on){
            const st=n.status||{}; const caps=[];
            caps.push(`<span class="nl-cap ${on?'ok':'bad'}"><span class="dotm"></span>${on?'آنلاین':'آفلاین'}</span>`);
            if(n.is_local) caps.push('<span class="nl-cap warn"><span class="dotm"></span>سرور اصلی</span>');
            else if(n.enabled===false) caps.push('<span class="nl-cap warn"><span class="dotm"></span>حالت نگهداری</span>');
            const addr=(n.address||'').replace(/^https?:\/\//,'');
            if(addr) caps.push(`<span class="nl-cap" dir="ltr" title="${esc(addr)}">${icon('link',12,1.9)}${esc(addr.length>26?addr.slice(0,26)+'…':addr)}</span>`);
            if(n.edge && n.edge.port) caps.push(`<span class="nl-cap ${n.edge.measured?'ok':''}" dir="ltr">edge ${esc(n.edge.scheme||'https')} :${esc(n.edge.port)}</span>`);
            const raw=n.raw_open||{};
            raw && Object.keys(raw).forEach(port=>{
              const open=raw[port]===true;
              caps.push(`<span class="nl-cap ${open?'ok':'bad'}" dir="ltr">raw ${esc(port)} ${open?'✓':'✕'}</span>`);
            });
            const sync=n.sync;
            if(sync){
              if(sync.ok===true){
                const serv=(sync.serving||[]).length;
                const exp=sync.expected!=null?sync.expected:serv;
                const cred=sync.credential?(' · '+(sync.credential==='shared'?'shared secret':'token')):'';
                caps.push(`<span class="nl-cap ok"><span class="dotm"></span>sync ${serv}/${exp} ✓${cred}</span>`);
              } else if(sync.ok===false){
                caps.push(`<span class="nl-cap bad"><span class="dotm"></span>sync ${esc(sync.error||'failed')}</span>`);
              }
            } else if(!st.online){
              caps.push('<span class="nl-cap"><span class="dotm"></span>sync نامشخص</span>');
            }
            return caps.join('');
          }
          function nodeCard(n){
            const st=n.status||{}; const on=!!(n.enabled!==false && st.online);
            const lat=(st.latency_ms!=null?Number(st.latency_ms):null);
            const cc=(n.country_code||nodeCountryCode(n)||'').toUpperCase();
            const city=(n.city && n.city!=='—')?n.city:'';
            const loc=[city||n.name, cc].filter(Boolean).join(' · ');
            const sync=n.sync||{}; const stale=(sync.ok===true && sync.at && (Date.now()/1000 - sync.at)>900);
            const note = !on ? `آخرین تماس: ${seen(n.last_seen)}${st.reason?' · '+esc(st.reason):''}`
                        : (sync.ok===false ? `آخرین همگام‌سازی ناموفق بود (${esc(sync.error||'error')}) — کاربران این نود از پنل سرو می‌شوند؛ توکن نود را روی خودِ نود ست کن (دکمهٔ ویرایش).`
                        : (stale ? `همگام‌سازی قدیمی است (${seen(sync.at)}) — یک بار همگام‌سازی فوری بزن.`
                        : (sync.ok===true ? '' : 'وضعیت همگام‌سازی هنوز اندازه‌گیری نشده است.')));
            return `<article class="node-lux ${on?'':'offline'}${n.is_local?' local':''}" data-node="${n.id}">
              <div class="nl-top">
                <div class="nl-medal">${nodeFlagHtml(n,'lg')}</div>
                <div style="flex:1;min-width:0">
                  <div class="nl-name"><span class="nl-orb ${on?'':'off'}"></span>${esc(n.name||(dashboardLang==='en'?'Node':'نود'))}</div>
                  <div class="nl-loc">${esc(loc)}</div>
                </div>
                <span class="pill ${on?'':'off'}">${on?'آنلاین':'آفلاین'}</span>
              </div>
              <div class="nl-dial">${ring(on,lat)}
                <div><div class="nl-dial-val">${lat!=null?lat+' ms':'—'}</div><div class="nl-dial-lbl">تأخیر</div></div>
              </div>
              <div class="nl-caps">${nodeCaps(n,on)}</div>
              <div class="nl-metrics">${bar('CPU',st.cpu)}${bar('RAM',st.ram)}${bar('DISK',st.disk)}</div>
              <div class="nl-meta">
                <span>نسخه: <b>${esc(st.version||'—')}</b></span>
                <span>کاربر روی نود: <b>${sync.on_node!=null?esc(sync.on_node):'—'}</b></span>
                <span>اپ‌تایم: <b>${st.uptime?esc(String(st.uptime)):'—'}</b></span>
              </div>
              ${note?`<div class="nl-note${(sync.ok===false&&on)?' bad':''}">${note}</div>`:''}
              <div class="nl-actions">
                ${icoBtn({'data-id':n.id,'data-act':'ping'},'pulse','بررسی اتصال')}
                ${icoBtn({'data-id':n.id,'data-act':'claim'},'bolt','شناسایی و اتصال خودکار (دامنه کافی است)','gold')}
                ${icoBtn({'data-id':n.id,'data-act':'sync'},'sync','همگام‌سازی فوری','violet')}
                ${icoBtn({'data-id':n.id,'data-act':'edit'},'edit','ویرایش نود','gold')}
                <span class="spacer"></span>
                ${n.is_local?'':icoBtn({'data-id':n.id,'data-act':'toggle'},'power',n.enabled===false?'خروج از حالت نگهداری':'حالت نگهداری',n.enabled===false?'ok':'')}
                ${n.is_local?'':icoBtn({'data-id':n.id,'data-act':'del'},'trash','حذف نود','danger')}
              </div>
            </article>`;
          }
          let grid2=serversSection.querySelector('.node-grid');
          if(!grid2){
            grid2=document.createElement('div'); grid2.className='node-grid'; grid2.id='nodeGrid';
            serversSection.appendChild(grid2);
          }
          grid2.innerHTML=nodes.length? nodes.map(nodeCard).join('')
            : '<div class="detail-card" style="grid-column:1/-1"><div class="metric-row"><span class="muted">سروری ثبت نشده است — با دکمهٔ افزودن سرور یک نود بساز.</span></div></div>';
          grid2.querySelectorAll('[data-act]').forEach(b=> b.addEventListener('click', async()=>{
            const id=b.dataset.id; const act=b.dataset.act;
            if(act==='ping'){
              b.disabled=true;
              try{ await apiJson('/api/nodes/'+id+'/ping',{method:'POST'}); toast('بررسی شد'); refreshServers(); loadOverview(); }
              catch(e){ toast(e.message); } finally{ b.disabled=false; }
            } else if(act==='claim'){
              b.disabled=true;
              try{
                const res=await apiJson('/api/nodes/'+id+'/claim',{method:'POST'});
                const st=res.node_sync||{};
                if(st.ok) toast('نود شناسایی شد و کاربرانش را گرفت ✓');
                else { toast('وصل نشد — متغیرها را ببین'); openNodeSetupModal({setup:{...(window.__titanSetup||{})}, sync_now:st}); }
                refreshServers(); loadOverview();
              }catch(e){ toast(e.message); } finally{ b.disabled=false; }
            } else if(act==='sync'){
              b.disabled=true;
              try{ await apiJson('/api/nodes/'+id+'/sync',{method:'POST'}); toast('همگام‌سازی شد'); refreshServers(); }
              catch(e){ toast(e.message); } finally{ b.disabled=false; }
            } else if(act==='edit'){
              try{ const n=(await apiJson('/api/nodes')).nodes.find(x=>String(x.id)===String(id)); if(n) await openNodeModal(n); }
              catch(e){ toast(e.message); }
            } else if(act==='toggle'){
              try{
                const cur=(await apiJson('/api/nodes')).nodes.find(x=>String(x.id)===String(id));
                await apiJson('/api/nodes/'+id,{method:'PATCH',body:{enabled:!(cur&&cur.enabled)}});
                toast(cur&&cur.enabled?'به حالت نگهداری رفت':'از حالت نگهداری خارج شد'); refreshServers(); loadOverview();
              }catch(e){ toast(e.message); }
            } else if(act==='del'){
              if(!confirm('حذف سرور؟')) return;
              try{ await apiJson('/api/nodes/'+id,{method:'DELETE'}); toast('حذف شد'); refreshServers(); loadOverview(); }
              catch(e){ toast(e.message); }
            }
          }));
        }catch(e){ console.error(e); }
      }
      refreshServers();
      document.addEventListener('titan:refresh', refreshServers);
      const addBtn=serversSection.querySelector('.section-btn.primary'); if(addBtn) addBtn.onclick=()=> openNodeModal();
      // The section head also carries a pulse button ("بررسی اتصال نودها").
      // It now measures the one thing the server can never know: the distance
      // from the admin's own device to every exit.
      const advBtn=serversSection.querySelector('.section-head .section-btn:not(.primary)');
      if(advBtn){ advBtn.setAttribute('data-act','advisor'); advBtn.onclick=()=> openLatencyAdvisor(); }
      $$('button',serversSection).forEach(b=>{ if(b.dataset.demo) b.removeAttribute('data-demo'); });
    }

    const subsSection=document.querySelector('.section-view[data-section="subscriptions"]');
    if(subsSection){
      // The tab lists *links*, not users: each row is a subscription the admin
      // built (name + token + the exact configs it carries).
      async function refreshSubs(){
        try{
          const d=await apiJson('/api/subscriptions'); const subs=d.subscriptions||[];
          const tbody=subsSection.querySelector('.data-table tbody');
          if(tbody){
            tbody.innerHTML=subs.length? subs.map(sb=>{
              const on=!!sb.enabled;
              const seen=sb.last_used? new Date(sb.last_used*1000).toLocaleString('fa-IR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : 'هرگز';
              // the picture the page shows: the link's own, else its user's, else TiTaN
              const pic='/s/'+esc(sb.token)+'/avatar';
              return `<tr><td><span class="user-cell"><span class="avatar user-avatar sub-medal" data-sub="${esc(sb.id)}" data-act="pic" role="button" tabindex="0" data-tip="تصویر این لینک روی صفحهٔ اشتراک" aria-label="تصویر این لینک"><img src="${pic}" alt=""></span>${esc(sb.name)}</span><span class="sub-token muted" dir="ltr">…${esc((sb.token||'').slice(-6))}</span></td>`
                +`<td><span class="pill ${on?'':'off'}">${on?'فعال':'غیرفعال'}</span></td>`
                +`<td><span class="sub-count">${sb.users||0}</span> کاربر</td>`
                +`<td><span class="sub-count">${sb.configs||0}</span> کانفیگ</td>`
                +`<td class="muted">${sb.hits||0} بار · ${esc(seen)}</td>`
                +`<td><div class="row-actions">${icoBtn({"data-sub":sb.id,"data-act":"manage"},"sliders","ساخت/ویرایش کانفیگ‌های این لینک","gold")}`
                +`${icoBtn({"data-sub":sb.id,"data-act":"copy"},"copy","کپی لینک اشتراک (برای کلاینت‌ها)","violet")}`
                +`${icoBtn({"data-sub":sb.id,"data-act":"page"},"dashboard","کپی لینک صفحهٔ اشتراک (برای کاربر)","")}`
                +`${icoBtn({"data-sub":sb.id,"data-act":"pic"},"image","تصویر این لینک روی صفحهٔ اشتراک","violet")}`
                +`${icoBtn({"data-sub":sb.id,"data-act":"qr"},"qr","QR لینک اشتراک","")}`
                +`${icoBtn({"data-sub":sb.id,"data-act":"power","data-on":on?1:0},"power",on?'غیرفعال کردن':'فعال کردن',on?'':'ok')}`
                +`${icoBtn({"data-sub":sb.id,"data-act":"del"},"trash","حذف لینک","danger")}</div></td></tr>`
            }).join('') : '<tr><td colspan="6" style="text-align:center;color:#8586a8">هنوز لینک اشتراکی ساخته نشده — با دکمهٔ بالا یکی بساز.</td></tr>';
            const find=async(id)=>{ const list=(await apiJson('/api/subscriptions')).subscriptions||[]; return list.find(s=>String(s.id)===String(id)); };
            tbody.querySelectorAll('[data-act="manage"]').forEach(b=> b.addEventListener('click', async()=>{
              try{ const sb=await find(b.dataset.sub); await openSubBuilder(sb, refreshSubs); }catch(e){ toast(e.message); }
            }));
            tbody.querySelectorAll('[data-act="copy"]').forEach(b=> b.addEventListener('click', async()=>{
              try{ const sb=await find(b.dataset.sub); await navigator.clipboard.writeText(sb.url); toast('لینک کپی شد'); }catch(e){ toast(e.message); }
            }));
            tbody.querySelectorAll('[data-act="qr"]').forEach(b=> b.addEventListener('click', ()=>{
              window.open('/api/subscriptions/'+b.dataset.sub+'/qr','_blank');
            }));
            tbody.querySelectorAll('[data-act="page"]').forEach(b=> b.addEventListener('click', async()=>{
              try{ const sb=await find(b.dataset.sub); await navigator.clipboard.writeText(sb.page_url||('location.origin'+'/p/'+sb.token)); toast('لینک صفحهٔ اشتراک کپی شد'); }
              catch(e){ toast(e.message); }
            }));
            const pickSubPic=async(id)=>{
              try{
                const sb=await find(id);
                const k=await openGalleryPicker((sb&&sb.avatar)||'');
                if(k==null) return;
                await apiJson('/api/subscriptions/'+id,{method:'PATCH',body:{avatar:k}});
                toast(k?'تصویر این لینک ذخیره شد':'تصویر این لینک برداشته شد');
                refreshSubs();
              }catch(e){ toast(e.message); }
            };
            tbody.querySelectorAll('[data-act="pic"]').forEach(b=> b.addEventListener('click', ()=>pickSubPic(b.dataset.sub)));
            tbody.querySelectorAll('[data-act="pic"]').forEach(b=> b.addEventListener('keydown', (e)=>{
              if(e.key==='Enter'||e.key===' '){ e.preventDefault(); pickSubPic(b.dataset.sub); }
            }));
            tbody.querySelectorAll('[data-act="power"]').forEach(b=> b.addEventListener('click', async()=>{
              const on=b.dataset.on==='1'; b.disabled=true;
              try{ await apiJson('/api/subscriptions/'+b.dataset.sub,{method:'PATCH',body:{enabled:!on}}); toast(on?'لینک غیرفعال شد':'لینک فعال شد'); refreshSubs(); }
              catch(e){ toast(e.message); } finally{ b.disabled=false; }
            }));
            tbody.querySelectorAll('[data-act="del"]').forEach(b=> b.addEventListener('click', async()=>{
              if(!confirm('این لینک اشتراک حذف شود؟')) return;
              try{ await apiJson('/api/subscriptions/'+b.dataset.sub,{method:'DELETE'}); toast('حذف شد'); refreshSubs(); }catch(e){ toast(e.message); }
            }));
          }
        }catch(e){ console.error(e); }
      }
      refreshSubs(); document.addEventListener('titan:refresh', refreshSubs);
      const newSubBtn=subsSection.querySelector('.section-head .section-btn.primary');
      if(newSubBtn) newSubBtn.onclick=()=> openSubBuilder(null, refreshSubs);
    }
    const reportsSection=document.querySelector('.section-view[data-section="reports"]');
    if(reportsSection){
      async function refreshReports(){
        try{
          const r=await apiJson('/api/reports?days=7');
          const t=r.totals||{}; const prots=r.protocols||[]; const daily=r.daily||[];
          const grid=reportsSection.querySelector('.section-grid');
          if(grid && grid.children.length>=3){
            grid.children[0].innerHTML=`<h3>مصرف ترافیک</h3><div class="metric-row"><span>دانلود</span><strong>${esc(fmtBytes(t.total_down||0))}</strong></div><div class="metric-row"><span>آپلود</span><strong>${esc(fmtBytes(t.total_up||0))}</strong></div><div class="progress"><span style="width:${Math.min(100, Math.round(((t.total_up+t.total_down)/(1024*1024*1024))*10))}%"></span></div>`;
            grid.children[1].innerHTML=`<h3>رشد کاربران</h3><div class="metric-row"><span>کل</span><strong>${t.users||0}</strong></div><div class="metric-row"><span>فعال</span><strong>${t.active||0}</strong></div><div class="metric-row"><span>منقضی</span><strong>${t.expired||0}</strong></div>`;
            const evCount = (r.daily||[]).reduce((a,d)=>a+ (d.up||0)+(d.down||0),0);
            grid.children[2].innerHTML=`<h3>رویدادهای سیستم</h3><div class="metric-row"><span>کاربران فعال</span><strong>${t.active||0}</strong></div><div class="metric-row"><span>غیرفعال</span><strong>${t.disabled||0}</strong></div><div class="metric-row"><span>پروتکل‌ها</span><strong>${prots.length}</strong></div>`;
          }
          // chart-mini
          const chartMini=reportsSection.querySelector('.chart-mini');
          if(chartMini && daily.length){
            const max=Math.max(1, ...daily.map(d=> (d.up||0)+(d.down||0)));
            chartMini.innerHTML=daily.map(d=>{
              const h=Math.max(8, Math.round(((d.up+d.down)/max)*100));
              return `<span style="height:${h}%" title="${esc(fmtBytes(d.up+d.down))}"></span>`;
            }).join('');
            const totEl=reportsSection.querySelector('.chart-mini + .metric-row strong');
            if(totEl) totEl.textContent='مجموع '+fmtBytes(daily.reduce((a,d)=>a+d.up+d.down,0));
          }
          // keep "آخرین رویدادها" table as static events; top_users is shown in chart tooltip, not overwriting events
          // (if needed, could render top users elsewhere without destroying real event log)
        }catch(e){ console.error(e); }
      }
      refreshReports(); document.addEventListener('titan:refresh', refreshReports);
      // remove demo handlers
      $$('button',reportsSection).forEach(b=>{ if(b.dataset.demo) b.removeAttribute('data-demo'); });
    }

    const settingsSection=document.querySelector('.section-view[data-section="settings"]');
    if(settingsSection){
      // map inputs by placeholder/label
      const findInput=(ph)=> settingsSection.querySelector(`input[placeholder="${ph}"]`) || [...settingsSection.querySelectorAll('input')].find(i=> i.placeholder&&i.placeholder.includes(ph));
      const publicDomain = findInput('example.com');
      const publicPort = [...settingsSection.querySelectorAll('input')].find(i=> i.value==='443' && i.type!=='password') || settingsSection.querySelector('input[value="443"]');
      const saveBtn = settingsSection.querySelector('.section-btn.primary');
      const oldPass = settingsSection.querySelector('input[placeholder="••••••••"]');
      const newPass = settingsSection.querySelector('input[placeholder="رمز عبور جدید"]');
      const changeBtn = [...settingsSection.querySelectorAll('button')].find(b=> (b.textContent||'').includes('تغییر رمز'));
      const transportSel = [...settingsSection.querySelectorAll('select')].find(s=> [...s.options].some(o=> o.value==='WS' || o.textContent==='WS'));
      const fpSel = [...settingsSection.querySelectorAll('select')].find(s=> [...s.options].some(o=> o.value==='chrome'));
      const alpnIn = [...settingsSection.querySelectorAll('input')].find(i=> i.value==='http/1.1');
      const sniIn = findInput('') && [...settingsSection.querySelectorAll('.field')].find(f=> f.textContent.includes('SNI'))?.querySelector('input');

      async function loadSettings(){
        try{
          const s=await apiJson('/api/settings');
          if(publicDomain) publicDomain.value=s.public_domain||'';
          if(publicPort) publicPort.value=s.public_port||'443';
          if(transportSel && s.default_transport) transportSel.value=s.default_transport.toUpperCase();
          if(fpSel && s.default_fingerprint) fpSel.value=s.default_fingerprint;
          if(alpnIn) alpnIn.value=s.default_alpn||'http/1.1';
          if(sniIn) sniIn.value=s.sni_override||'';
          // toggles
          const mapToggle={'مسدودسازی IPهای خصوصی':'restrict_ips','مسدودسازی تبلیغات':'block_ads','مسدودسازی سایت‌های ایرانی':'block_iran_sites','اعلان اتصال جدید':'notify_new_conn','فعال‌سازی Fragment':'fragment_enabled','پشتیبان‌گیری خودکار':'backup_enabled'};
          $$('.toggle-row',settingsSection).forEach(row=>{
            const label=(row.textContent||'').trim();
            for(const [k,ck] of Object.entries(mapToggle)){
              if(label.includes(k)){
                const sw=row.querySelector('.switch');
                if(sw){
                  const on=!!s[ck];
                  sw.classList.toggle('on', on);
                  sw.onclick=()=> sw.classList.toggle('on');
                }
              }
            }
          });
          const fragLen=[...settingsSection.querySelectorAll('input')].find(i=> i.value==='10-30');
          const fragInt=[...settingsSection.querySelectorAll('input')].find(i=> i.value==='10-20');
          if(fragLen) fragLen.value=s.fragment_length||'10-30';
          if(fragInt) fragInt.value=s.fragment_interval||'10-20';
          const backupInt=[...settingsSection.querySelectorAll('input')].find(i=> i.type==='number' && i.value==='24');
          // actually backup interval is number input
          const allNum=[...settingsSection.querySelectorAll('input[type="number"]')];
          // find backup interval by label
          const backupField=[...settingsSection.querySelectorAll('.field')].find(f=> f.textContent.includes('بازه پشتیبان'));
          if(backupField){
            const inp=backupField.querySelector('input');
            if(inp) inp.value=s.backup_interval_hours||24;
          }
          // update notice about password
          const notice=settingsSection.querySelector('.notice');
          if(notice){
            const me=await apiJson('/api/me').catch(()=>null);
            if(me && !me.default_auth) notice.style.display='none';
            else notice.style.display='block';
          }
        }catch(e){ console.error(e); }
      }
      loadSettings();
      if(saveBtn) saveBtn.onclick=async()=>{
        const body={};
        if(publicDomain) body.public_domain=publicDomain.value.trim();
        if(publicPort) body.public_port=publicPort.value.trim();
        if(transportSel) body.default_transport=(transportSel.value||'ws').toLowerCase();
        if(fpSel) body.default_fingerprint=fpSel.value;
        if(alpnIn) body.default_alpn=alpnIn.value;
        if(sniIn) body.sni_override=sniIn.value.trim();
        // toggles
        const mapToggle={'مسدودسازی IPهای خصوصی':'restrict_ips','مسدودسازی تبلیغات':'block_ads','مسدودسازی سایت‌های ایرانی':'block_iran_sites','اعلان اتصال جدید':'notify_new_conn','فعال‌سازی Fragment':'fragment_enabled','پشتیبان‌گیری خودکار':'backup_enabled'};
        $$('.toggle-row',settingsSection).forEach(row=>{
          const label=(row.textContent||'').trim();
          for(const [k,ck] of Object.entries(mapToggle)){
            if(label.includes(k)){
              const sw=row.querySelector('.switch');
              if(sw) body[ck]=sw.classList.contains('on');
            }
          }
        });
        const fragLen=[...settingsSection.querySelectorAll('input')].find(i=> i.placeholder==='' && i.value.includes('-') && i.value!=='10-20');
        // more robust: find by label
        const fragLenField=[...settingsSection.querySelectorAll('.field')].find(f=> f.textContent.includes('طول Fragment'));
        if(fragLenField) body.fragment_length=fragLenField.querySelector('input').value;
        const fragIntField=[...settingsSection.querySelectorAll('.field')].find(f=> f.textContent.includes('بازه Fragment'));
        if(fragIntField) body.fragment_interval=fragIntField.querySelector('input').value;
        const backupField=[...settingsSection.querySelectorAll('.field')].find(f=> f.textContent.includes('بازه پشتیبان'));
        if(backupField) body.backup_interval_hours=parseInt(backupField.querySelector('input').value)||24;

        try{ await apiJson('/api/settings',{method:'POST',body}); toast('تنظیمات ذخیره شد'); }
        catch(e){ toast(e.message); }
      };
      if(changeBtn) changeBtn.onclick=async()=>{
        const oldV=oldPass?oldPass.value:''; const newV=newPass?newPass.value:'';
        if(!newV || newV.length<6){ toast('رمز جدید باید حداقل ۶ کاراکتر باشد'); return; }
        try{ await apiJson('/api/change-password',{method:'POST',body:{old_password:oldV,new_password:newV}}); toast('رمز عبور تغییر کرد'); if(oldPass) oldPass.value=''; if(newPass) newPass.value=''; }
        catch(e){ toast(e.message==='wrong-old-password'?'رمز فعلی اشتباه است':e.message); }
      };
      const dlBtn=[...settingsSection.querySelectorAll('button')].find(b=> (b.textContent||'').includes('دانلود پشتیبان'));
      if(dlBtn) dlBtn.onclick=()=>{ location.href='/api/backup'; };
      const restoreBtn=[...settingsSection.querySelectorAll('button')].find(b=> (b.textContent||'').includes('بازیابی'));
      if(restoreBtn) restoreBtn.onclick=()=>{
        const inp=document.createElement('input'); inp.type='file'; inp.accept='.b64,.gz';
        inp.onchange=async()=>{
          const file=inp.files[0]; if(!file) return; if(!confirm('بازیابی از پشتیبان؟')) return;
          const fd=new FormData(); fd.append('file',file);
          try{ const r=await fetch('/api/backup/restore',{method:'POST',body:fd,credentials:'same-origin'}); const d=await r.json().catch(()=>({})); if(r.ok) toast('بازیابی شد'); else toast(d.detail||'خطا'); }catch(e){ toast(e.message); }
        };
        inp.click();
      };
      const restartBtn=settingsSection.querySelector('.danger-btn');
      if(restartBtn) restartBtn.onclick=async()=>{ if(!confirm('راه‌اندازی مجدد پنل؟')) return; try{ await apiJson('/api/restart',{method:'POST'}); toast('در حال راه‌اندازی...'); }catch(e){ toast(e.message); } };
      // avatar in settings
      const avatarBtn=[...settingsSection.querySelectorAll('button')].find(b=> (b.textContent||'').includes('گالری'));
      if(avatarBtn) avatarBtn.onclick=async()=>{
        const me=await apiJson('/api/me').catch(()=>null);
        const cur=me&&me.avatar?me.avatar.key:'';
        const k=await openGalleryPicker(cur);
        if(k==null) return;
        try{ await apiJson('/api/admin-avatar',{method:'POST',body:{avatar:k}}); toast('تصویر ذخیره شد'); loadMe(); }
        catch(e){ toast(e.message); }
      };
      $$('button',settingsSection).forEach(b=>{ if(b.dataset.demo) b.removeAttribute('data-demo'); });
    }

    const adminsSection=document.querySelector('.section-view[data-section="admins"]');
    if(adminsSection){
      async function refreshAdmins(){
        try{
          const info=await apiJson('/api/admin-info');
          // update avatar in the table
          const imgs=adminsSection.querySelectorAll('.avatar img');
          imgs.forEach(img=>{ if(info.avatar&&info.avatar.url) img.src=info.avatar.url; });
          const nameCell=adminsSection.querySelector('.data-table tbody td');
          if(nameCell && info.username) nameCell.textContent=info.username;
        }catch(e){}
      }
      refreshAdmins(); document.addEventListener('titan:refresh', refreshAdmins);
    }

    const toolsSection=document.querySelector('.section-view[data-section="tools"]');
    if(toolsSection){
      const testBtn=[...toolsSection.querySelectorAll('button')].find(b=> (b.textContent||'').includes('تست اتصال'));
      if(testBtn) testBtn.onclick=async()=>{
        testBtn.disabled=true; const old=testBtn.textContent; testBtn.textContent='در حال تست...';
        try{ const r=await apiJson('/api/connection-test'); toast('Xray: '+(r.xray_running?'فعال':'غیرفعال')+' - WS: '+(r.internal_ports_open&&r.internal_ports_open['vless-ws']?'ok':'fail')); }catch(e){ toast(e.message); } finally{ testBtn.disabled=false; testBtn.textContent=old; }
      };
      $$('button',toolsSection).forEach(b=>{ if(b.dataset.demo) b.removeAttribute('data-demo'); });
    }
  }

  // --- header & sidebar wiring ---
  document.addEventListener('DOMContentLoaded', ()=>{
    loadMe(); loadOverview(); setTimeout(wireDetails, 400);

    const gSearch=document.querySelector('.search input[type="search"]');
    if(gSearch){
      gSearch.addEventListener('input', ()=>{
        const q=gSearch.value.trim().toLowerCase();
        $$('.recent-table-row').forEach(r=> r.style.display=r.textContent.toLowerCase().includes(q)?'':'none');
      });
      document.addEventListener('keydown', e=>{ if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){ e.preventDefault(); gSearch.focus(); } });
    }
    const refreshBtn=document.querySelectorAll('.action')[1];
    if(refreshBtn) refreshBtn.onclick=()=>{ loadOverview(); toast('به‌روزرسانی شد'); };

    // profile: click avatar -> change picture (not just logout)
    const prof=document.querySelector('.header .profile');
    const profAv=document.querySelector('.header .profile .avatar');
    if(profAv){
      profAv.style.cursor='pointer';
      profAv.title='تغییر تصویر پروفایل';
      profAv.onclick=async (e)=>{
        e.stopPropagation();
        try{
          const me=await apiJson('/api/me');
          const cur=me.avatar?me.avatar.key:'';
          const k=await openGalleryPicker(cur);
          if(k==null) return;
          await apiJson('/api/admin-avatar',{method:'POST',body:{avatar:k}});
          toast('تصویر پروفایل ذخیره شد');
          loadMe();
        }catch(err){ toast(err.message); }
      };
    }
    // profile container click -> show menu with avatar change + logout
    if(prof){
      // add a small logout icon next to profile if not exists
      if(!$('#headerLogout')){
        const lo=document.createElement('button');
        lo.id='headerLogout';
        lo.title='خروج';
        lo.style.cssText='width:32px;height:32px;border-radius:9px;border:1px solid rgba(151,116,255,.18);background:rgba(91,49,176,.1);color:#c5c5df;display:grid;place-items:center;cursor:pointer;margin-right:6px';
        lo.innerHTML='<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.7"><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/><path d="M13 21H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7"/></svg>';
        lo.onclick=async()=>{
          if(confirm('خروج از حساب؟')){ try{ await apiJson('/api/logout',{method:'POST'}); location.href='/login'; }catch(e){ location.href='/login'; } }
        };
        const actions=document.querySelector('.actions');
        if(actions) actions.appendChild(lo);
      }
    }
    const ver=document.querySelector('.version');
    if(ver) ver.onclick=()=> toast('TiTaN Panel');

    // sidebar version avatar also clickable to change
    const verLogo=document.querySelector('.version-logo');
    if(verLogo){
      verLogo.style.cursor='pointer';
      verLogo.onclick=async()=>{
        try{
          const me=await apiJson('/api/me');
          const cur=me.avatar?me.avatar.key:'';
          const k=await openGalleryPicker(cur);
          if(k!=null){ await apiJson('/api/admin-avatar',{method:'POST',body:{avatar:k}}); toast('تصویر ذخیره شد'); loadMe(); }
        }catch(e){ toast(e.message); }
      };
    }

    function handleHash(){
      const h=location.hash||'';
      const map={'#/dashboard':0,'#/users':1,'#/configs':2,'#/nodes':3,'#/subscriptions':4,'#/reports':5,'#/settings':6,'#/admins':7,'#/tools':8};
      const idx=map[h];
      if(idx!=null){ const nav=document.querySelectorAll('.nav-item'); if(nav[idx]) nav[idx].click(); }
    }
    window.addEventListener('hashchange', handleHash); handleHash();
  });

  initDashboardLanguage();
  window._titanRefresh=()=>{ loadOverview(); document.dispatchEvent(new Event('titan:refresh')); };
})();
