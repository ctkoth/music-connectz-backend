// Music ConnectZ v9.2 - Global i18n Configuration with Geo-Relevant Content & Referral System
window.I18N_CONFIG = {
  defaultLang: 'en-US',
  currentLang: localStorage.getItem('mcz_lang') || 'en-US',
  
  languages: {
    // English
    'en-US': { name: '🇺🇸 English (United States)', nativeName: 'English' },
    'en-GB': { name: '🇬🇧 English (United Kingdom)', nativeName: 'English' },
    'en-CA': { name: '🇨🇦 English (Canada)', nativeName: 'English' },
    'en-AU': { name: '🇦🇺 English (Australia)', nativeName: 'English' },
    'en-NZ': { name: '🇳🇿 English (New Zealand)', nativeName: 'English' },
    'en-ZA': { name: '🇿🇦 English (South Africa)', nativeName: 'English' },
    // Spanish
    'es-ES': { name: '🇪🇸 Español (España)', nativeName: 'Español' },
    'es-MX': { name: '🇲🇽 Español (México)', nativeName: 'Español' },
    'es-AR': { name: '🇦🇷 Español (Argentina)', nativeName: 'Español' },
    'es-CO': { name: '🇨🇴 Español (Colombia)', nativeName: 'Español' },
    'es-CL': { name: '🇨🇱 Español (Chile)', nativeName: 'Español' },
    'es-PE': { name: '🇵🇪 Español (Perú)', nativeName: 'Español' },
    // Portuguese
    'pt-BR': { name: '🇧🇷 Português (Brasil)', nativeName: 'Português' },
    'pt-PT': { name: '🇵🇹 Português (Portugal)', nativeName: 'Português' },
    // French
    'fr-FR': { name: '🇫🇷 Français (France)', nativeName: 'Français' },
    'fr-CA': { name: '🇨🇦 Français (Canada)', nativeName: 'Français' },
    // German
    'de-DE': { name: '🇩🇪 Deutsch (Deutschland)', nativeName: 'Deutsch' },
    // Italian
    'it-IT': { name: '🇮🇹 Italiano (Italia)', nativeName: 'Italiano' },
    // Dutch
    'nl-NL': { name: '🇳🇱 Nederlands (Nederland)', nativeName: 'Nederlands' },
    'nl-BE': { name: '🇧🇪 Nederlands (België)', nativeName: 'Nederlands' },
    // Russian
    'ru-RU': { name: '🇷🇺 Русский (Россия)', nativeName: 'Русский' },
    // Chinese
    'zh-CN': { name: '🇨🇳 中文(中国)', nativeName: '中文' },
    'zh-TW': { name: '🇹🇼 中文(台灣)', nativeName: '中文' },
    'zh-HK': { name: '🇭🇰 中文(香港)', nativeName: '中文' },
    // Japanese
    'ja-JP': { name: '🇯🇵 日本語 (日本)', nativeName: '日本語' },
    // Korean
    'ko-KR': { name: '🇰🇷 한국어 (대한민국)', nativeName: '한국어' },
    // Hindi
    'hi-IN': { name: '🇮🇳 हिंदी (भारत)', nativeName: 'हिंदी' },
    // Arabic
    'ar-SA': { name: '🇸🇦 العربية (السعودية)', nativeName: 'العربية' },
    'ar-EG': { name: '🇪🇬 العربية (مصر)', nativeName: 'العربية' },
    // Turkish
    'tr-TR': { name: '🇹🇷 Türkçe (Türkiye)', nativeName: 'Türkçe' },
    // Polish
    'pl-PL': { name: '🇵🇱 Polski (Polska)', nativeName: 'Polski' },
    // Swedish
    'sv-SE': { name: '🇸🇪 Svenska (Sverige)', nativeName: 'Svenska' },
    // Finnish
    'fi-FI': { name: '🇫🇮 Suomi (Suomi)', nativeName: 'Suomi' },
    // Norwegian
    'no-NO': { name: '🇳🇴 Norsk (Norge)', nativeName: 'Norsk' },
    // Danish
    'da-DK': { name: '🇩🇰 Dansk (Danmark)', nativeName: 'Dansk' },
    // Czech
    'cs-CZ': { name: '🇨🇿 Čeština (Česko)', nativeName: 'Čeština' },
    // Slovak
    'sk-SK': { name: '🇸🇰 Slovenčina (Slovensko)', nativeName: 'Slovenčina' },
    // Ukrainian
    'uk-UA': { name: '🇺🇦 Українська (Україна)', nativeName: 'Українська' },
    // Greek
    'el-GR': { name: '🇬🇷 Ελληνικά (Ελλάδα)', nativeName: 'Ελληνικά' },
    // Thai
    'th-TH': { name: '🇹🇭 ไทย (ประเทศไทย)', nativeName: 'ไทย' },
    // Indonesian
    'id-ID': { name: '🇮🇩 Bahasa Indonesia (Indonesia)', nativeName: 'Bahasa Indonesia' },
    // Filipino
    'fil-PH': { name: '🇵🇭 Filipino (Pilipinas)', nativeName: 'Filipino' },
    // Malay
    'ms-MY': { name: '🇲🇾 Bahasa Melayu (Malaysia)', nativeName: 'Bahasa Melayu' },
    // Vietnamese
    'vi-VN': { name: '🇻🇳 Tiếng Việt (Việt Nam)', nativeName: 'Tiếng Việt' },
    // Hungarian
    'hu-HU': { name: '🇭🇺 Magyar (Magyarország)', nativeName: 'Magyar' },
    // Hebrew
    'he-IL': { name: '🇮🇱 עברית (ישראל)', nativeName: 'עברית' },
    // Bengali
    'bn-BD': { name: '🇧🇩 বাংলা (বাংলাদেশ)', nativeName: 'বাংলা' },
    // Swahili
    'sw-KE': { name: '🇰🇪 Kiswahili (Kenya)', nativeName: 'Kiswahili' },
    // More can be added as needed
  },

  translations: {
    'en-US': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: 'Find Local Collaborators Fast • Verified Profiles • Skill-Based Matching',
      auth_subtitle: 'Sign in fast with verified social accounts and start matching with local collaborators.',
      guest_banner: 'Log in to unlock matching, messaging, and verified collaborations.',
      connected_accounts_helper: 'Link multiple providers so you can sign in your way and recover access faster.',
      
      // Referral System
      referral_title: 'Earn Rewards',
      referral_subtitle: 'Invite friends and unlock exclusive benefits',
      referral_link_label: 'Your Referral Link',
      referral_copy_btn: 'Copy Link',
      referral_share_twitter: 'Share on Twitter',
      referral_share_whatsapp: 'Share on WhatsApp',
      referral_stats: 'Your Referral Stats',
      referral_invited: 'Friends Invited',
      referral_joined: 'Friends Joined',
      referral_rewards: 'Rewards Earned',
      referral_tier: 'Current Tier',
      
      // Referral Tiers
      referral_tier_bronze: '🥉 Bronze',
      referral_tier_silver: '🥈 Silver',
      referral_tier_gold: '🥇 Gold',
      referral_tier_platinum: '💎 Platinum',
      
      referral_bronze_desc: '0-2 referrals',
      referral_silver_desc: '3-5 referrals',
      referral_gold_desc: '6-10 referrals',
      referral_platinum_desc: '10+ referrals',
      
      referral_bronze_reward: '$5 credit',
      referral_silver_reward: '$5 credit + 1 mo premium',
      referral_gold_reward: '$25 credit + 3 mo premium',
      referral_platinum_reward: '$50 credit + 6 mo premium + priority support',
      
      // Auth
      sign_up: 'Sign Up',
      password_help: 'Password must be at least 8 characters, contain a number, a lowercase and an uppercase letter.',
      show_passwords: 'Show Passwords',
      login_register: 'Login or Register with Email or Social Account',
      continue_auth: 'Continue Auth on Secure Server',
      
      // Personas (US/English focus on commercial music)
      persona_artist: 'Independent Artist',
      persona_designer: 'Visual Designer',
      persona_engineer: 'Mix Engineer',
      persona_ghostwriter: 'Ghostwriter',
      persona_manager: 'Business Manager',
      persona_producer: 'Beat Producer',
      persona_videographer: 'Videographer',
      
      persona_artist_desc: 'Creates and performs original music, shaping the creative direction and identity of a project.',
      persona_designer_desc: 'Builds the visual identity of music brands and releases across digital and print media.',
      persona_engineer_desc: 'Delivers technical audio quality through recording, mixing, editing, and mastering.',
      persona_ghostwriter_desc: 'Creates lyrics, hooks, and concepts for artists while remaining behind the scenes.',
      persona_manager_desc: 'Leads career operations, partnerships, and long-term strategy for artists and teams.',
      persona_producer_desc: 'Shapes the sound, arrangement, and creative execution of tracks from idea to release.',
      persona_videographer_desc: 'Produces video content that strengthens artist branding, storytelling, and promotion.',
      
      // US Genres
      genres_hiphop: 'Hip-Hop',
      genres_rnb: 'R&B/Soul',
      genres_pop: 'Pop',
      genres_indie: 'Indie',
      genres_electronic: 'Electronic',
      genres_country: 'Country',
      genres_rock: 'Rock',
      genres_latin: 'Reggaeton/Latin',
      genres_jazz: 'Jazz',
      genres_gospel: 'Gospel',
      
      // v9.2 Updates
      updates_title: 'v9.2 Updates',
      updates_subtitle: 'Now available in 10 languages with geo-relevant content',
      updates_i18n: 'Complete internationalization with local genre & skill recommendations',
      updates_referral: 'Tiered referral rewards system - earn credits and premium access',
      updates_geo: 'Geo-optimized collaboration discovery and local artist matching',
      updates_version: 'Version and release date auto-updated',
    },

    'en-GB': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: 'Find Local Collaborators Fast • Verified Profiles • Skill-Based Matching',
      auth_subtitle: 'Sign in quickly with verified social accounts and begin matching with local musicians.',
      guest_banner: 'Log in to unlock matching, messaging, and verified collaborations.',
      connected_accounts_helper: 'Link multiple providers so you can sign in your way and recover access quicker.',
      
      referral_title: 'Earn Rewards',
      referral_subtitle: 'Invite friends and unlock exclusive benefits',
      referral_link_label: 'Your Referral Link',
      referral_copy_btn: 'Copy Link',
      referral_share_twitter: 'Share on Twitter',
      referral_share_whatsapp: 'Share on WhatsApp',
      referral_stats: 'Your Referral Stats',
      referral_invited: 'Friends Invited',
      referral_joined: 'Friends Joined',
      referral_rewards: 'Rewards Earned',
      referral_tier: 'Current Tier',
      
      referral_tier_bronze: '🥉 Bronze',
      referral_tier_silver: '🥈 Silver',
      referral_tier_gold: '🥇 Gold',
      referral_tier_platinum: '💎 Platinum',
      
      referral_bronze_desc: '0-2 referrals',
      referral_silver_desc: '3-5 referrals',
      referral_gold_desc: '6-10 referrals',
      referral_platinum_desc: '10+ referrals',
      
      referral_bronze_reward: '£4 credit',
      referral_silver_reward: '£4 credit + 1 mo premium',
      referral_gold_reward: '£20 credit + 3 mo premium',
      referral_platinum_reward: '£40 credit + 6 mo premium + priority support',
      
      sign_up: 'Sign Up',
      password_help: 'Password must be at least 8 characters, contain a number, a lowercase and an uppercase letter.',
      show_passwords: 'Show Passwords',
      login_register: 'Login or Register with Email or Social Account',
      continue_auth: 'Continue Auth on Secure Server',
      
      persona_artist: 'Independent Artist',
      persona_designer: 'Visual Designer',
      persona_engineer: 'Mix Engineer',
      persona_ghostwriter: 'Ghostwriter',
      persona_manager: 'Business Manager',
      persona_producer: 'Beat Producer',
      persona_videographer: 'Videographer',
      
      persona_artist_desc: 'Creates and performs original music, shaping the creative direction and identity of a project.',
      persona_designer_desc: 'Designs the visual identity of music brands and releases across digital and print media.',
      persona_engineer_desc: 'Delivers professional audio quality through recording, mixing, editing, and mastering.',
      persona_ghostwriter_desc: 'Creates lyrics, hooks, and concepts for artists whilst remaining behind the scenes.',
      persona_manager_desc: 'Leads career operations, partnerships, and long-term strategy for artists and teams.',
      persona_producer_desc: 'Shapes the sound, arrangement, and creative execution of tracks from idea to release.',
      persona_videographer_desc: 'Produces video content that strengthens artist branding, storytelling, and promotion.',
      
      genres_hiphop: 'Hip-Hop',
      genres_rnb: 'R&B/Soul',
      genres_pop: 'Pop',
      genres_indie: 'Indie/Alternative',
      genres_electronic: 'Electronic/Grime',
      genres_country: 'Country/Folk',
      genres_rock: 'Rock/Punk',
      genres_latin: 'Latin/Reggaeton',
      genres_jazz: 'Jazz/Funk',
      genres_gospel: 'Gospel/Choir',
      
      updates_title: 'v9.2 Updates',
      updates_subtitle: 'Now available in 10 languages with geo-relevant content',
      updates_i18n: 'Complete internationalization with local genre & skill recommendations',
      updates_referral: 'Tiered referral rewards system - earn credits and premium access',
      updates_geo: 'Geo-optimised collaboration discovery and local artist matching',
      updates_version: 'Version and release date auto-updated',
    },

    'pt-BR': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: 'Encontre Colaboradores Locais Rápido • Perfis Verificados • Matching por Habilidades',
      auth_subtitle: 'Conecte-se rápido com contas sociais verificadas e comece a combinar com colaboradores locais.',
      guest_banner: 'Faça login para desbloquear matching, mensagens e colaborações verificadas.',
      connected_accounts_helper: 'Conecte múltiplas contas para fazer login do seu jeito e recuperar acesso mais rápido.',
      
      referral_title: 'Ganhe Recompensas',
      referral_subtitle: 'Convide amigos e desbloqueie benefícios exclusivos',
      referral_link_label: 'Seu Link de Indicação',
      referral_copy_btn: 'Copiar Link',
      referral_share_twitter: 'Compartilhar no Twitter',
      referral_share_whatsapp: 'Compartilhar no WhatsApp',
      referral_stats: 'Suas Estatísticas de Indicação',
      referral_invited: 'Amigos Convidados',
      referral_joined: 'Amigos Aderidos',
      referral_rewards: 'Recompensas Ganhas',
      referral_tier: 'Nível Atual',
      
      referral_tier_bronze: '🥉 Bronze',
      referral_tier_silver: '🥈 Prata',
      referral_tier_gold: '🥇 Ouro',
      referral_tier_platinum: '💎 Platina',
      
      referral_bronze_desc: '0-2 indicações',
      referral_silver_desc: '3-5 indicações',
      referral_gold_desc: '6-10 indicações',
      referral_platinum_desc: '10+ indicações',
      
      referral_bronze_reward: 'R$25 de crédito',
      referral_silver_reward: 'R$25 de crédito + 1 mês premium',
      referral_gold_reward: 'R$100 de crédito + 3 meses premium',
      referral_platinum_reward: 'R$200 de crédito + 6 meses premium + suporte prioritário',
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 Welcome to Music ConnectZ!', content: 'Find collaborators, grow your network, and unlock rewards. Let’s get started!' },
        { title: '🔍 Discover Talent', content: 'Browse verified profiles by skill, genre, and location. Tap a card to view details.' },
        { title: '🤝 Match & Message', content: 'Send invites or messages to connect instantly. Use filters for best results.' },
        { title: '🎁 Earn Rewards', content: 'Invite friends with your referral link to unlock credits and premium features.' },
        { title: '🌐 Go Global', content: 'Switch languages anytime for a local experience. Enjoy music collaboration worldwide!' }
      ],
      
      sign_up: 'Cadastro',
      password_help: 'Senha deve ter no mínimo 8 caracteres, contendo número, letra minúscula e maiúscula.',
      show_passwords: 'Mostrar Senhas',
      login_register: 'Login ou Cadastro com Email ou Rede Social',
      continue_auth: 'Continuar Autenticação no Servidor Seguro',
      
      persona_artist: 'Artista Independente',
      persona_designer: 'Designer Visual',
      persona_engineer: 'Engenheiro de Mixagem',
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 Bem-vindo ao Music ConnectZ!', content: 'Encontre colaboradores, expanda sua rede e ganhe recompensas. Vamos começar!' },
        { title: '🔍 Descubra Talentos', content: 'Explore perfis verificados por habilidade, gênero e localização. Toque para ver detalhes.' },
        { title: '🤝 Combine & Converse', content: 'Envie convites ou mensagens para se conectar. Use filtros para melhores resultados.' },
        { title: '🎁 Ganhe Recompensas', content: 'Convide amigos com seu link para desbloquear créditos e recursos premium.' },
        { title: '🌐 Experiência Global', content: 'Altere o idioma a qualquer momento para uma experiência local. Colabore com músicos do mundo todo!' }
      ],
      persona_ghostwriter: 'Compositor Contratado',
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 Bem-vindo ao Music ConnectZ!', content: 'Encontre colaboradores, expanda sua rede e ganhe prémios. Vamos começar!' },
        { title: '🔍 Descubra Talentos', content: 'Explore perfis verificados por competência, género e localização. Toque para ver detalhes.' },
        { title: '🤝 Combine & Converse', content: 'Envie convites ou mensagens para se ligar. Use filtros para melhores resultados.' },
        { title: '🎁 Ganhe Prémios', content: 'Convide amigos com sua ligação para desbloquear créditos e recursos premium.' },
        { title: '🌐 Experiência Global', content: 'Altere o idioma a qualquer momento para uma experiência local. Colabore com músicos do mundo inteiro!' }
      ],
      persona_manager: 'Gerente de Negócios',
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 Music ConnectZ에 오신 것을 환영합니다!', content: '협력자를 찾고, 네트워크를 확장하고, 보상을 받으세요. 시작해볼까요?' },
        { title: '🔍 인재 발견', content: '기술, 장르, 위치별로 검증된 프로필을 탐색하세요. 카드를 눌러 세부 정보를 확인하세요.' },
        { title: '🤝 매칭 & 메시지', content: '즉시 연결하려면 초대 또는 메시지를 보내세요. 필터를 사용해 최적의 결과를 얻으세요.' },
        { title: '🎁 보상 받기', content: '추천 링크로 친구를 초대해 크레딧과 프리미엄 기능을 잠금 해제하세요.' },
        { title: '🌐 글로벌 경험', content: '언어를 언제든지 변경해 현지화된 경험을 즐기세요. 전 세계 음악 협업을 경험하세요!' }
      ],
      persona_producer: 'Produtor de Beats',
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 欢迎来到 Music ConnectZ！', content: '寻找合作者，拓展人脉，赢取奖励。让我们开始吧！' },
        { title: '🔍 发现人才', content: '按技能、流派和位置浏览已验证的个人资料。点击卡片查看详情。' },
        { title: '🤝 匹配与消息', content: '发送邀请或消息即可即时联系。使用筛选器获得最佳结果。' },
        { title: '🎁 获得奖励', content: '用您的推荐链接邀请朋友，解锁积分和高级功能。' },
        { title: '🌐 全球体验', content: '随时切换语言，享受本地化体验。畅享全球音乐协作！' }
      ],
      persona_videographer: 'Videógrafo',
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 歡迎來到 Music ConnectZ！', content: '尋找合作者，拓展人脈，贏取獎勵。讓我們開始吧！' },
        { title: '🔍 發現人才', content: '按技能、類型和地點瀏覽已驗證的個人資料。點擊卡片查看詳情。' },
        { title: '🤝 配對與訊息', content: '發送邀請或訊息即可即時聯繫。使用篩選器獲得最佳結果。' },
        { title: '🎁 獲得獎勵', content: '用您的推薦連結邀請朋友，解鎖積點和高級功能。' },
        { title: '🌐 全球體驗', content: '隨時切換語言，享受本地化體驗。暢享全球音樂協作！' }
      ],
      
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 Music ConnectZへようこそ！', content: 'コラボ相手を見つけ、ネットワークを広げ、報酬を獲得しましょう。さあ始めましょう！' },
        { title: '🔍 タレントを発見', content: 'スキル、ジャンル、場所で認証済みプロフィールを閲覧。カードをタップして詳細を確認。' },
        { title: '🤝 マッチ＆メッセージ', content: '招待やメッセージで即座に繋がろう。フィルターで最適な相手を見つけよう。' },
        { title: '🎁 報酬を獲得', content: '紹介リンクで友人を招待し、クレジットやプレミアム機能をアンロック。' },
        { title: '🌐 グローバル体験', content: 'いつでも言語を切り替えてローカル体験。世界中の音楽コラボを楽しもう！' }
      ],
      persona_artist_desc: 'Cria e performatiza música original, moldando a direção criativa e identidade do projeto.',
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 مرحبًا بك في Music ConnectZ!', content: 'ابحث عن متعاونين، نمِّ شبكتك، واكسب المكافآت. لنبدأ!' },
        { title: '🔍 اكتشف المواهب', content: 'تصفح الملفات الموثقة حسب المهارة والنوع والموقع. اضغط لعرض التفاصيل.' },
        { title: '🤝 طابق وأرسل رسالة', content: 'أرسل دعوات أو رسائل للاتصال الفوري. استخدم الفلاتر لأفضل النتائج.' },
        { title: '🎁 اكسب مكافآت', content: 'ادعُ أصدقاءك برابط الإحالة لفتح الرصيد والمزايا المميزة.' },
        { title: '🌐 تجربة عالمية', content: 'بدّل اللغة في أي وقت لتجربة محلية. استمتع بالتعاون الموسيقي حول العالم!' }
      ],
      persona_designer_desc: 'Constrói a identidade visual de marcas musicais e lançamentos em mídia digital e impressa.',
      // Onboarding Tour Steps
      onboarding_tour_steps: [
        { title: '👋 Music ConnectZ में आपका स्वागत है!', content: 'सहयोगी खोजें, नेटवर्क बढ़ाएँ, और पुरस्कार अर्जित करें। चलिए शुरू करें!' },
        { title: '🔍 प्रतिभा खोजें', content: 'कौशल, शैली और स्थान के अनुसार सत्यापित प्रोफाइल ब्राउज़ करें। विवरण देखने के लिए टैप करें।' },
        { title: '🤝 मैच और संदेश', content: 'कनेक्ट करने के लिए आमंत्रण या संदेश भेजें। सर्वोत्तम परिणामों के लिए फ़िल्टर का उपयोग करें।' },
        { title: '🎁 पुरस्कार अर्जित करें', content: 'अपने रेफरल लिंक से दोस्तों को आमंत्रित करें और क्रेडिट व प्रीमियम फीचर्स अनलॉक करें।' },
        { title: '🌐 वैश्विक अनुभव', content: 'कभी भी भाषा बदलें और स्थानीय अनुभव पाएं। विश्वभर के संगीत सहयोग का आनंद लें!' }
      ],
      persona_engineer_desc: 'Entrega qualidade técnica de áudio através de gravação, mixagem, edição e masterização.',
      persona_ghostwriter_desc: 'Cria letras, ganchos e conceitos para artistas enquanto permanece nos bastidores.',
      persona_manager_desc: 'Lidera operações de carreira, parcerias e estratégia de longo prazo para artistas e equipes.',
      persona_producer_desc: 'Molda o som, arranjo e execução criativa de faixas da ideia até o lançamento.',
      persona_videographer_desc: 'Produz conteúdo de vídeo que fortalece branding do artista, storytelling e promoção.',
      
      genres_hiphop: 'Hip-Hop/Trap',
      genres_rnb: 'R&B/Soul',
      genres_pop: 'Pop/Funk Carioca',
      genres_indie: 'Indie',
      genres_electronic: 'Eletrônico/EDM',
      genres_country: 'Sertanejo/Folk',
      genres_rock: 'Rock/MPB',
      genres_latin: 'Reggaeton/Música Latina',
      genres_jazz: 'Jazz/Bossa Nova',
      genres_gospel: 'Gospel/Louvação',
      
      updates_title: 'Atualizações v9.2',
      updates_subtitle: 'Agora disponível em 10 idiomas com conteúdo localizado',
      updates_i18n: 'Internacionalização completa com recomendações de gênero e habilidade locais',
      updates_referral: 'Sistema de recompensas de indicação escalonado - ganhe créditos e acesso premium',
      updates_geo: 'Descoberta de colaboração otimizada geograficamente e matching de artistas locais',
      updates_version: 'Versão e data de lançamento atualizadas automaticamente',
    },

    'pt-PT': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: 'Encontre Colaboradores Locais Rápido • Perfis Verificados • Matching por Competências',
      auth_subtitle: 'Conecte-se rapidamente com contas sociais verificadas e comece a colaborar com músicos locais.',
      guest_banner: 'Inicie sessão para desbloquear matching, mensagens e colaborações verificadas.',
      connected_accounts_helper: 'Ligue múltiplas contas para iniciar sessão à sua maneira e recuperar acesso mais rapidamente.',
      
      referral_title: 'Ganhe Prémios',
      referral_subtitle: 'Convide amigos e desbloqueie benefícios exclusivos',
      referral_link_label: 'Sua Ligação de Recomendação',
      referral_copy_btn: 'Copiar Ligação',
      referral_share_twitter: 'Partilhar no Twitter',
      referral_share_whatsapp: 'Partilhar no WhatsApp',
      referral_stats: 'Suas Estatísticas de Recomendação',
      referral_invited: 'Amigos Convidados',
      referral_joined: 'Amigos Aderidos',
      referral_rewards: 'Prémios Ganhos',
      referral_tier: 'Nível Actual',
      
      referral_tier_bronze: '🥉 Bronze',
      referral_tier_silver: '🥈 Prata',
      referral_tier_gold: '🥇 Ouro',
      referral_tier_platinum: '💎 Platina',
      
      referral_bronze_desc: '0-2 recomendações',
      referral_silver_desc: '3-5 recomendações',
      referral_gold_desc: '6-10 recomendações',
      referral_platinum_desc: '10+ recomendações',
      
      referral_bronze_reward: '€4 de crédito',
      referral_silver_reward: '€4 de crédito + 1 mês premium',
      referral_gold_reward: '€20 de crédito + 3 meses premium',
      referral_platinum_reward: '€40 de crédito + 6 meses premium + apoio prioritário',
      
      sign_up: 'Registar',
      password_help: 'A palavra-passe deve ter pelo menos 8 caracteres, contendo um número, uma letra minúscula e maiúscula.',
      show_passwords: 'Mostrar Palavras-Passe',
      login_register: 'Iniciar Sessão ou Registar com Email ou Rede Social',
      continue_auth: 'Continuar Autenticação no Servidor Seguro',
      
      persona_artist: 'Artista Independente',
      persona_designer: 'Designer Visual',
      persona_engineer: 'Engenheiro de Mistura',
      persona_ghostwriter: 'Compositor Fantasma',
      persona_manager: 'Gestor de Negócios',
      persona_producer: 'Produtor de Beats',
      persona_videographer: 'Videógrafo',
      
      persona_artist_desc: 'Cria e interpreta música original, moldando a direcção criativa e identidade do projecto.',
      persona_designer_desc: 'Constrói a identidade visual de marcas musicais e lançamentos em mídia digital e impressa.',
      persona_engineer_desc: 'Entrega qualidade técnica de áudio através de gravação, mixagem, edição e masterização.',
      persona_ghostwriter_desc: 'Cria letras, ganchos e conceitos para artistas enquanto permanece nos bastidores.',
      persona_manager_desc: 'Lidera operações de carreira, parcerias e estratégia de longo prazo para artistas e equipas.',
      persona_producer_desc: 'Molda o som, arranjo e execução criativa de faixas da ideia até ao lançamento.',
      persona_videographer_desc: 'Produz conteúdo de vídeo que fortalece branding do artista, storytelling e promoção.',
      
      genres_hiphop: 'Hip-Hop/Trap',
      genres_rnb: 'R&B/Soul',
      genres_pop: 'Pop/Indie',
      genres_indie: 'Indie/Alternative',
      genres_electronic: 'Electrónico/Techno',
      genres_country: 'Folk/Fado',
      genres_rock: 'Rock/Metal',
      genres_latin: 'Reggaeton/Música Latina',
      genres_jazz: 'Jazz/Bossa Nova',
      genres_gospel: 'Gospel/Cânticos',
      
      updates_title: 'Actualizações v9.2',
      updates_subtitle: 'Agora disponível em 10 idiomas com conteúdo localizado',
      updates_i18n: 'Internacionalização completa com recomendações de género e competências locais',
      updates_referral: 'Sistema de prémios de recomendação escalonado - ganhe créditos e acesso premium',
      updates_geo: 'Descoberta de colaboração optimizada geograficamente e matching de artistas locais',
      updates_version: 'Versão e data de lançamento actualizadas automaticamente',
    },

    'ko-KR': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: '빠르게 지역 협력자 찾기 • 검증된 프로필 • 스킬 기반 매칭',
      auth_subtitle: '검증된 소셜 계정으로 빠르게 로그인하고 지역 협력자와의 매칭을 시작하세요.',
      guest_banner: '로그인하여 매칭, 메시징, 검증된 협업을 잠금 해제하세요.',
      connected_accounts_helper: '여러 계정을 연결하여 원하는 방식으로 로그인하고 더 빠르게 액세스를 복구하세요.',
      
      referral_title: '보상 받기',
      referral_subtitle: '친구를 초대하고 독점 혜택을 잠금 해제하세요',
      referral_link_label: '당신의 추천 링크',
      referral_copy_btn: '링크 복사',
      referral_share_twitter: 'Twitter에서 공유',
      referral_share_whatsapp: 'WhatsApp에서 공유',
      referral_stats: '당신의 추천 통계',
      referral_invited: '초대된 친구',
      referral_joined: '가입한 친구',
      referral_rewards: '얻은 보상',
      referral_tier: '현재 등급',
      
      referral_tier_bronze: '🥉 브론즈',
      referral_tier_silver: '🥈 실버',
      referral_tier_gold: '🥇 골드',
      referral_tier_platinum: '💎 플래티넘',
      
      referral_bronze_desc: '0-2 추천',
      referral_silver_desc: '3-5 추천',
      referral_gold_desc: '6-10 추천',
      referral_platinum_desc: '10+ 추천',
      
      referral_bronze_reward: '$5 크레딧',
      referral_silver_reward: '$5 크레딧 + 1개월 프리미엄',
      referral_gold_reward: '$25 크레딧 + 3개월 프리미엄',
      referral_platinum_reward: '$50 크레딧 + 6개월 프리미엄 + 우선 지원',
      
      sign_up: '회원가입',
      password_help: '비밀번호는 최소 8자, 숫자, 소문자, 대문자를 포함해야 합니다.',
      show_passwords: '비밀번호 표시',
      login_register: '이메일 또는 소셜 계정으로 로그인 또는 가입',
      continue_auth: '보안 서버에서 인증 계속',
      
      persona_artist: '독립 아티스트',
      persona_designer: '비주얼 디자이너',
      persona_engineer: '믹스 엔지니어',
      persona_ghostwriter: '고스트라이터',
      persona_manager: '비즈니스 매니저',
      persona_producer: '비트 프로듀서',
      persona_videographer: '비디오그래퍼',
      
      persona_artist_desc: '원곡을 제작하고 공연하며 프로젝트의 창의적 방향과 정체성을 형성합니다.',
      persona_designer_desc: '디지털 및 인쇄 매체 전반에 걸쳐 음악 브랜드 및 출시의 시각적 정체성을 구축합니다.',
      persona_engineer_desc: '녹음, 믹싱, 편집 및 마스터링을 통해 기술적 오디오 품질을 제공합니다.',
      persona_ghostwriter_desc: '아티스트를 위해 가사, 훅, 개념을 만들면서 뒤에 머물러 있습니다.',
      persona_manager_desc: '아티스트 및 팀의 커리어 운영, 파트너십 및 장기 전략을 주도합니다.',
      persona_producer_desc: '아이디어에서 출시까지 트랙의 사운드, 편곡 및 창의적 실행을 형성합니다.',
      persona_videographer_desc: '아티스트 브랜딩, 스토리텔링 및 홍보를 강화하는 비디오 콘텐츠를 제작합니다.',
      
      genres_hiphop: '힙합/트랩',
      genres_rnb: 'R&B/솔',
      genres_pop: 'K-pop/팝',
      genres_indie: '인디/얼터너티브',
      genres_electronic: '일렉트로닉',
      genres_country: '포크/트로트',
      genres_rock: '록/메탈',
      genres_latin: '라틴/레게톤',
      genres_jazz: '재즈/보사노바',
      genres_gospel: '캐롤/속가요',
      
      updates_title: 'v9.2 업데이트',
      updates_subtitle: '이제 10개 언어로 지역화된 콘텐츠와 함께 제공됩니다',
      updates_i18n: '로컬 장르 및 스킬 추천이 있는 완전한 국제화',
      updates_referral: '계층화된 추천 보상 시스템 - 크레딧 및 프리미엄 액세스 획득',
      updates_geo: '지역 최적화된 협업 발견 및 로컬 아티스트 매칭',
      updates_version: '버전 및 출시 날짜 자동 업데이트',
    },

    'zh-CN': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: '快速寻找本地合作者 • 已验证的个人资料 • 基于技能的匹配',
      auth_subtitle: '使用经过验证的社交账户快速登录，开始与本地合作者匹配。',
      guest_banner: '登录以解锁匹配、消息传递和经过验证的协作。',
      connected_accounts_helper: '连接多个账户，以您的方式登录，更快地恢复访问权限。',
      
      referral_title: '获得奖励',
      referral_subtitle: '邀请朋友并解锁独家福利',
      referral_link_label: '您的推荐链接',
      referral_copy_btn: '复制链接',
      referral_share_twitter: '在Twitter上分享',
      referral_share_whatsapp: '在WhatsApp上分享',
      referral_stats: '您的推荐统计',
      referral_invited: '邀请的朋友',
      referral_joined: '已加入的朋友',
      referral_rewards: '获得的奖励',
      referral_tier: '当前等级',
      
      referral_tier_bronze: '🥉 青铜',
      referral_tier_silver: '🥈 白银',
      referral_tier_gold: '🥇 黄金',
      referral_tier_platinum: '💎 白金',
      
      referral_bronze_desc: '0-2 次推荐',
      referral_silver_desc: '3-5 次推荐',
      referral_gold_desc: '6-10 次推荐',
      referral_platinum_desc: '10+ 次推荐',
      
      referral_bronze_reward: '$5 积分',
      referral_silver_reward: '$5 积分 + 1个月高级会员',
      referral_gold_reward: '$25 积分 + 3个月高级会员',
      referral_platinum_reward: '$50 积分 + 6个月高级会员 + 优先支持',
      
      sign_up: '注册',
      password_help: '密码必须至少8个字符，包含数字、小写字母和大写字母。',
      show_passwords: '显示密码',
      login_register: '使用电子邮件或社交账户登录或注册',
      continue_auth: '在安全服务器上继续身份验证',
      
      persona_artist: '独立音乐人',
      persona_designer: '视觉设计师',
      persona_engineer: '混音工程师',
      persona_ghostwriter: '幽灵写手',
      persona_manager: '业务经理',
      persona_producer: '节拍制作人',
      persona_videographer: '摄像师',
      
      persona_artist_desc: '创作和表演原创音乐，塑造项目的创意方向和身份。',
      persona_designer_desc: '在数字和印刷媒体上构建音乐品牌和发布的视觉标识。',
      persona_engineer_desc: '通过录音、混音、编辑和母带处理提供技术音频质量。',
      persona_ghostwriter_desc: '为艺术家创作歌词、音钩和概念，同时保持幕后角色。',
      persona_manager_desc: '领导艺术家和团队的职业运营、合作伙伴关系和长期战略。',
      persona_producer_desc: '从构想到发行塑造曲目的声音、编排和创意执行。',
      persona_videographer_desc: '制作加强艺术家品牌、故事叙述和推广的视频内容。',
      
      genres_hiphop: '嘻哈/陷阱',
      genres_rnb: 'R&B/灵魂乐',
      genres_pop: '流行/国风',
      genres_indie: '独立/另类',
      genres_electronic: '电子/EDM',
      genres_country: '民谣/戏曲',
      genres_rock: '摇滚/重金属',
      genres_latin: '雷鬼/拉丁',
      genres_jazz: '爵士/波萨诺瓦',
      genres_gospel: '福音/唱诗班',
      
      updates_title: 'v9.2 更新',
      updates_subtitle: '现在提供10种语言的本地化内容',
      updates_i18n: '完整的国际化，包括本地流派和技能推荐',
      updates_referral: '分级推荐奖励系统 - 赚取积分和高级访问权限',
      updates_geo: '地理优化的协作发现和本地艺术家匹配',
      updates_version: '版本和发布日期自动更新',
    },

    'zh-TW': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: '快速尋找本地合作者 • 已驗證的個人資料 • 基於技能的配對',
      auth_subtitle: '使用經過驗證的社交帳戶快速登入，開始與本地合作者配對。',
      guest_banner: '登入以解鎖配對、通訊和經過驗證的協作。',
      connected_accounts_helper: '連結多個帳戶，以您的方式登入，更快地恢復存取權限。',
      
      referral_title: '獲得獎勵',
      referral_subtitle: '邀請朋友並解鎖獨家福利',
      referral_link_label: '您的推薦連結',
      referral_copy_btn: '複製連結',
      referral_share_twitter: '在Twitter上分享',
      referral_share_whatsapp: '在WhatsApp上分享',
      referral_stats: '您的推薦統計',
      referral_invited: '邀請的朋友',
      referral_joined: '已加入的朋友',
      referral_rewards: '獲得的獎勵',
      referral_tier: '目前等級',
      
      referral_tier_bronze: '🥉 青銅',
      referral_tier_silver: '🥈 白銀',
      referral_tier_gold: '🥇 黃金',
      referral_tier_platinum: '💎 白金',
      
      referral_bronze_desc: '0-2 次推薦',
      referral_silver_desc: '3-5 次推薦',
      referral_gold_desc: '6-10 次推薦',
      referral_platinum_desc: '10+ 次推薦',
      
      referral_bronze_reward: '$5 積點',
      referral_silver_reward: '$5 積點 + 1個月高級會員',
      referral_gold_reward: '$25 積點 + 3個月高級會員',
      referral_platinum_reward: '$50 積點 + 6個月高級會員 + 優先支援',
      
      sign_up: '註冊',
      password_help: '密碼必須至少8個字元，包含數字、小寫字母和大寫字母。',
      show_passwords: '顯示密碼',
      login_register: '使用電子郵件或社交帳戶登入或註冊',
      continue_auth: '在安全伺服器上繼續身份驗證',
      
      persona_artist: '獨立音樂人',
      persona_designer: '視覺設計師',
      persona_engineer: '混音工程師',
      persona_ghostwriter: '幽靈寫手',
      persona_manager: '業務經理',
      persona_producer: '節拍製作人',
      persona_videographer: '攝影師',
      
      persona_artist_desc: '創作和表演原創音樂，塑造專案的創意方向和身份。',
      persona_designer_desc: '在數位和印刷媒體上構建音樂品牌和發行的視覺身份。',
      persona_engineer_desc: '通過錄音、混音、編輯和母帶處理提供技術音訊品質。',
      persona_ghostwriter_desc: '為藝術家創作歌詞、音鉤和概念，同時保持幕後角色。',
      persona_manager_desc: '領導藝術家和團隊的職業營運、合作夥伴關係和長期策略。',
      persona_producer_desc: '從構想到發行塑造曲目的聲音、編排和創意執行。',
      persona_videographer_desc: '製作加強藝術家品牌、故事敘述和推廣的視訊內容。',
      
      genres_hiphop: '嘻哈/陷阱',
      genres_rnb: 'R&B/靈魂樂',
      genres_pop: '流行/民俗',
      genres_indie: '獨立/另類',
      genres_electronic: '電子/EDM',
      genres_country: '民謠/民俗',
      genres_rock: '搖滾/重金屬',
      genres_latin: '雷鬼/拉丁',
      genres_jazz: '爵士/波薩諾瓦',
      genres_gospel: '福音/聖詩',
      
      updates_title: 'v9.2 更新',
      updates_subtitle: '現在提供10種語言的本地化內容',
      updates_i18n: '完整的國際化，包括本地音樂類型和技能推薦',
      updates_referral: '分級推薦獎勵系統 - 賺取積點和高級存取權限',
      updates_geo: '地理優化的協作發現和本地藝術家配對',
      updates_version: '版本和發布日期自動更新',
    },

    'ja-JP': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: '地元のコラボレーターを素早く見つける • 検証済みプロフィール • スキルベースのマッチング',
      auth_subtitle: '検証済みのソーシャルアカウントで素早くサインインし、地元のコラボレーターとのマッチングを開始してください。',
      guest_banner: 'ログインしてマッチング、メッセージング、検証済みの協業をアンロックしてください。',
      connected_accounts_helper: '複数のアカウントをリンクして、あなたの方法でサインインし、より迅速にアクセスを復旧してください。',
      
      referral_title: '報酬を獲得',
      referral_subtitle: '友人を招待して限定特典をアンロック',
      referral_link_label: 'あなたの紹介リンク',
      referral_copy_btn: 'リンクをコピー',
      referral_share_twitter: 'Twitterで共有',
      referral_share_whatsapp: 'WhatsAppで共有',
      referral_stats: 'あなたの紹介統計',
      referral_invited: '招待した友人',
      referral_joined: '参加した友人',
      referral_rewards: '獲得した報酬',
      referral_tier: '現在のティア',
      
      referral_tier_bronze: '🥉 ブロンズ',
      referral_tier_silver: '🥈 シルバー',
      referral_tier_gold: '🥇 ゴールド',
      referral_tier_platinum: '💎 プラチナ',
      
      referral_bronze_desc: '0-2件の紹介',
      referral_silver_desc: '3-5件の紹介',
      referral_gold_desc: '6-10件の紹介',
      referral_platinum_desc: '10件以上の紹介',
      
      referral_bronze_reward: '$5クレジット',
      referral_silver_reward: '$5クレジット + 1ヶ月プレミアム',
      referral_gold_reward: '$25クレジット + 3ヶ月プレミアム',
      referral_platinum_reward: '$50クレジット + 6ヶ月プレミアム + 優先サポート',
      
      sign_up: 'サインアップ',
      password_help: 'パスワードは最低8文字で、数字、小文字、大文字を含める必要があります。',
      show_passwords: 'パスワードを表示',
      login_register: 'メールまたはソーシャルアカウントでログインまたは登録',
      continue_auth: 'セキュアサーバーで認証を続行',
      
      persona_artist: 'インディーアーティスト',
      persona_designer: 'ビジュアルデザイナー',
      persona_engineer: 'ミックスエンジニア',
      persona_ghostwriter: 'ゴーストライター',
      persona_manager: 'ビジネスマネージャー',
      persona_producer: 'ビートプロデューサー',
      persona_videographer: 'ビデオグラファー',
      
      persona_artist_desc: 'オリジナル音楽を制作・演奏し、プロジェクトの創作方向とアイデンティティを形成します。',
      persona_designer_desc: 'デジタルとプリント媒体全体にわたってミュージックブランドとリリースのビジュアルアイデンティティを構築します。',
      persona_engineer_desc: '録音、ミキシング、編集、マスタリングを通じて技術的なオーディオ品質を提供します。',
      persona_ghostwriter_desc: '舞台裏に留まりながら、アーティストのために歌詞、フック、概念を作成します。',
      persona_manager_desc: 'アーティストとチームのキャリア運営、パートナーシップ、長期戦略をリードします。',
      persona_producer_desc: 'アイデアからリリースまでトラックのサウンド、アレンジメント、創作実行を形成します。',
      persona_videographer_desc: 'アーティストのブランディング、ストーリーテリング、プロモーションを強化するビデオコンテンツを制作します。',
      
      genres_hiphop: 'ヒップホップ/トラップ',
      genres_rnb: 'R&B/ソウル',
      genres_pop: 'J-POP/ポップ',
      genres_indie: 'インディー/オルタナティブ',
      genres_electronic: 'エレクトロニック/EDM',
      genres_country: 'フォーク/エモ',
      genres_rock: 'ロック/メタル',
      genres_latin: 'レゲエトン/ラテン',
      genres_jazz: 'ジャズ/ボサノバ',
      genres_gospel: 'ゴスペル/合唱',
      
      updates_title: 'v9.2アップデート',
      updates_subtitle: '10言語のローカライズされたコンテンツで利用可能',
      updates_i18n: 'ローカルジャンルとスキルのレコメンデーション付きの完全な国際化',
      updates_referral: '階層化された紹介報酬システム - クレジットとプレミアムアクセス獲得',
      updates_geo: '地理的に最適化されたコラボレーション発見とローカルアーティストマッチング',
      updates_version: 'バージョンと発行日の自動更新',
    },

    'ar-SA': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: 'ابحث عن متعاونين محليين بسرعة • ملفات شخصية موثقة • مطابقة قائمة على المهارات',
      auth_subtitle: 'قم بتسجيل الدخول بسرعة باستخدام حسابات اجتماعية موثقة وابدأ المطابقة مع المتعاونين المحليين.',
      guest_banner: 'قم بتسجيل الدخول لفتح المطابقة والرسائل والتعاون الموثق.',
      connected_accounts_helper: 'ربط عدة حسابات حتى تتمكن من تسجيل الدخول بطريقتك واستعادة الوصول بشكل أسرع.',
      
      referral_title: 'اكسب مكافآت',
      referral_subtitle: 'ادعُ أصدقاءك وافتح مزايا حصرية',
      referral_link_label: 'رابط الإحالة الخاص بك',
      referral_copy_btn: 'نسخ الرابط',
      referral_share_twitter: 'شارك على تويتر',
      referral_share_whatsapp: 'شارك عبر WhatsApp',
      referral_stats: 'إحصائيات الإحالة الخاصة بك',
      referral_invited: 'الأصدقاء المدعويون',
      referral_joined: 'الأصدقاء المنضمون',
      referral_rewards: 'المكافآت المكتسبة',
      referral_tier: 'المستوى الحالي',
      
      referral_tier_bronze: '🥉 برونزي',
      referral_tier_silver: '🥈 فضي',
      referral_tier_gold: '🥇 ذهبي',
      referral_tier_platinum: '💎 بلاتيني',
      
      referral_bronze_desc: '0-2 إحالة',
      referral_silver_desc: '3-5 إحالات',
      referral_gold_desc: '6-10 إحالات',
      referral_platinum_desc: '10+ إحالة',
      
      referral_bronze_reward: '5 دولارات رصيد',
      referral_silver_reward: '5 دولارات رصيد + شهر واحد مميز',
      referral_gold_reward: '25 دولار رصيد + 3 أشهر مميزة',
      referral_platinum_reward: '50 دولار رصيد + 6 أشهر مميزة + دعم الأولويات',
      
      sign_up: 'اشترك',
      password_help: 'يجب أن تحتوي كلمة المرور على 8 أحرف على الأقل وتحتوي على رقم وحرف صغير وحرف كبير.',
      show_passwords: 'إظهار كلمات المرور',
      login_register: 'تسجيل الدخول أو التسجيل باستخدام البريد الإلكتروني أو حساب اجتماعي',
      continue_auth: 'متابعة المصادقة على الخادم الآمن',
      
      persona_artist: 'فنان مستقل',
      persona_designer: 'مصمم بصري',
      persona_engineer: 'مهندس ميكس',
      persona_ghostwriter: 'كاتب خفي',
      persona_manager: 'مدير العمل',
      persona_producer: 'منتج إيقاعات',
      persona_videographer: 'مصور فيديو',
      
      persona_artist_desc: 'ينتج ويؤدي الموسيقى الأصلية، ويشكل الاتجاه الإبداعي وهوية المشروع.',
      persona_designer_desc: 'بناء الهوية البصرية لعلامات الموسيقى والإصدارات عبر الوسائط الرقمية والمطبوعة.',
      persona_engineer_desc: 'يوفر جودة صوتية تقنية من خلال التسجيل والمزج والتحرير والإتقان.',
      persona_ghostwriter_desc: 'ينشئ الكلمات والخطافات والمفاهيم للفنانين مع البقاء خلف الكواليس.',
      persona_manager_desc: 'يقود العمليات الوظيفية والشراكات والإستراتيجية طويلة المدى للفنانين والفرق.',
      persona_producer_desc: 'يشكل الصوت والترتيب والتنفيذ الإبداعي للمسارات من الفكرة إلى الإصدار.',
      persona_videographer_desc: 'ينتج محتوى فيديو يعزز علامة الفنان والسرد المرئي والترويج.',
      
      genres_hiphop: 'هيب هوب/تراب',
      genres_rnb: 'R&B/الروح',
      genres_pop: 'البوب/الخليج',
      genres_indie: 'مستقل/بديل',
      genres_electronic: 'إلكترونيات/EDM',
      genres_country: 'فولك/شرقي',
      genres_rock: 'روك/معدن',
      genres_latin: 'ريجيتون/لاتيني',
      genres_jazz: 'جاز/بوسانوفا',
      genres_gospel: 'إنجيل/قرآن',
      
      updates_title: 'تحديثات v9.2',
      updates_subtitle: 'متاح الآن بـ 10 لغات مع محتوى محلي',
      updates_i18n: 'عولمة كاملة مع توصيات الأنواع والمهارات المحلية',
      updates_referral: 'نظام مكافآت إحالة متدرج - اكسب الرصيد والوصول المميز',
      updates_geo: 'اكتشاف تعاون محسّن جغرافياً ومطابقة الفنانين المحليين',
      updates_version: 'إصدار وتاريخ الإصدار المحدث تلقائياً',
    },

    'hi-IN': {
      app_title: 'Music ConnectZ v9.2',
      app_subtitle: 'स्थानीय सहयोगियों को तेजी से खोजें • सत्यापित प्रोफाइलें • कौशल-आधारित मिलान',
      auth_subtitle: 'सत्यापित सोशल खातों के साथ तेजी से साइन इन करें और स्थानीय सहयोगियों के साथ मिलान शुरू करें।',
      guest_banner: 'मिलान, संदेशन और सत्यापित सहयोग को अनलॉक करने के लिए लॉगिन करें।',
      connected_accounts_helper: 'कई प्रदाताओं को लिंक करें ताकि आप अपने तरीके से साइन इन कर सकें और तेजी से एक्सेस पुनः प्राप्त कर सकें।',
      
      referral_title: 'पुरस्कार अर्जित करें',
      referral_subtitle: 'दोस्तों को आमंत्रित करें और अनन्य लाभ अनलॉक करें',
      referral_link_label: 'आपकी रेफरल लिंक',
      referral_copy_btn: 'लिंक कॉपी करें',
      referral_share_twitter: 'Twitter पर साझा करें',
      referral_share_whatsapp: 'WhatsApp पर साझा करें',
      referral_stats: 'आपके रेफरल सांख्यिकी',
      referral_invited: 'निमंत्रित दोस्त',
      referral_joined: 'शामिल हुए दोस्त',
      referral_rewards: 'अर्जित पुरस्कार',
      referral_tier: 'वर्तमान स्तर',
      
      referral_tier_bronze: '🥉 कांस्य',
      referral_tier_silver: '🥈 चांदी',
      referral_tier_gold: '🥇 सोना',
      referral_tier_platinum: '💎 प्लैटिनम',
      
      referral_bronze_desc: '0-2 रेफरल',
      referral_silver_desc: '3-5 रेफरल',
      referral_gold_desc: '6-10 रेफरल',
      referral_platinum_desc: '10+ रेफरल',
      
      referral_bronze_reward: '$5 क्रेडिट',
      referral_silver_reward: '$5 क्रेडिट + 1 माह प्रीमियम',
      referral_gold_reward: '$25 क्रेडिट + 3 माह प्रीमियम',
      referral_platinum_reward: '$50 क्रेडिट + 6 माह प्रीमियम + प्राथमिकता समर्थन',
      
      sign_up: 'साइन अप करें',
      password_help: 'पासवर्ड में कम से कम 8 वर्ण होने चाहिए, एक संख्या, एक लोअरकेस और एक अपरकेस अक्षर होना चाहिए।',
      show_passwords: 'पासवर्ड दिखाएं',
      login_register: 'ईमेल या सोशल खाते के साथ लॉगिन या पंजीकरण करें',
      continue_auth: 'सुरक्षित सर्वर पर प्रमाणीकरण जारी रखें',
      
      persona_artist: 'स्वतंत्र कलाकार',
      persona_designer: 'विजुअल डिज़ाइनर',
      persona_engineer: 'मिक्स इंजीनियर',
      persona_ghostwriter: 'घोस्टराइटर',
      persona_manager: 'व्यावसायिक प्रबंधक',
      persona_producer: 'बीट प्रोड्यूसर',
      persona_videographer: 'वीडियोग्राफर',
      
      persona_artist_desc: 'मूल संगीत बनाता है और प्रदर्शन करता है, परियोजना की रचनात्मक दिशा और पहचान को आकार देता है।',
      persona_designer_desc: 'डिजिटल और प्रिंट मीडिया में संगीत ब्रांडों और रिलीज की दृश्य पहचान बनाता है।',
      persona_engineer_desc: 'रिकॉर्डिंग, मिश्रण, संपादन और मास्टरिंग के माध्यम से तकनीकी ऑडियो गुणवत्ता प्रदान करता है।',
      persona_ghostwriter_desc: 'दृश्यों के पीछे रहते हुए कलाकारों के लिए गीत, हुक और अवधारणाएं बनाता है।',
      persona_manager_desc: 'कलाकारों और टीमों के लिए कैरियर संचालन, साझेदारी और दीर्घकालीन रणनीति का नेतृत्व करता है।',
      persona_producer_desc: 'विचार से लेकर रिलीज तक ट्रैक की ध्वनि, व्यवस्था और रचनात्मक निष्पादन को आकार देता है।',
      persona_videographer_desc: 'वीडियो सामग्री बनाता है जो कलाकार ब्रांडिंग, कहानी सुनाने और प्रचार को मजबूत करती है।',
      
      genres_hiphop: 'हिप-हॉप/ट्रैप',
      genres_rnb: 'R&B/आत्मा',
      genres_pop: 'बॉलीवुड/पॉप',
      genres_indie: 'स्वतंत्र/वैकल्पिक',
      genres_electronic: 'इलेक्ट्रॉनिक/EDM',
      genres_country: 'लोक/शास्त्रीय',
      genres_rock: 'रॉक/मेटल',
      genres_latin: 'रेगेटॉन/लैटिन',
      genres_jazz: 'जैज/बोसा नोवा',
      genres_gospel: 'गॉस्पेल/भजन',
      
      updates_title: 'v9.2 अपडेट',
      updates_subtitle: '10 भाषाओं में स्थानीयकृत सामग्री के साथ अब उपलब्ध',
      updates_i18n: 'स्थानीय शैली और कौशल सुझाव के साथ पूर्ण अंतर्राष्ट्रीयकरण',
      updates_referral: 'स्तरीय रेफरल पुरस्कार प्रणाली - क्रेडिट और प्रीमियम एक्सेस अर्जित करें',
      updates_geo: 'भौगोलिक रूप से अनुकूलित सहयोग खोज और स्थानीय कलाकार मिलान',
      updates_version: 'संस्करण और रिलीज तारीख स्वचालित रूप से अपडेट होते हैं',
    }
  },

  // Global referral tier configuration
  referralTiers: [
    { tier: 0, name: 'bronze', minReferrals: 0, maxReferrals: 2, rewardUSD: 5, rewardMonths: 0 },
    { tier: 1, name: 'silver', minReferrals: 3, maxReferrals: 5, rewardUSD: 5, rewardMonths: 1 },
    { tier: 2, name: 'gold', minReferrals: 6, maxReferrals: 10, rewardUSD: 25, rewardMonths: 3 },
    { tier: 3, name: 'platinum', minReferrals: 11, maxReferrals: 999, rewardUSD: 50, rewardMonths: 6 }
  ],

  // Utility functions
  t: function(key) {
    const lang = window.I18N_CONFIG.currentLang;
    return (window.I18N_CONFIG.translations[lang] && window.I18N_CONFIG.translations[lang][key]) || key;
  },

  setLanguage: function(langCode) {
    if (window.I18N_CONFIG.languages[langCode]) {
      window.I18N_CONFIG.currentLang = langCode;
      localStorage.setItem('mcz_lang', langCode);
      window.location.reload();
    }
  },

  getCurrentLanguage: function() {
    return window.I18N_CONFIG.currentLang;
  },

  getReferralTier: function(referralCount) {
    for (let tier of window.I18N_CONFIG.referralTiers) {
      if (referralCount >= tier.minReferrals && referralCount <= tier.maxReferrals) {
        return tier;
      }
    }
    return window.I18N_CONFIG.referralTiers[0];
  }
};

// Auto-detect language if not set
if (!localStorage.getItem('mcz_lang') && typeof navigator !== 'undefined') {
  const userLang = navigator.language || navigator.userLanguage;
  const supportedLangs = Object.keys(window.I18N_CONFIG.languages);
  const detectedLang = supportedLangs.find(lang => userLang.startsWith(lang.split('-')[0])) || 'en-US';
  window.I18N_CONFIG.currentLang = detectedLang;
  localStorage.setItem('mcz_lang', detectedLang);
}
