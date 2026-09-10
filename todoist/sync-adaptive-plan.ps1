param(
    [string]$TokenPath = 'C:\Users\Bergmann\Desktop\angular\sicherheit\todoist.txt',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ApiBase = 'https://api.todoist.com/api/v1'
$ProjectName = 'План Мусафира'
$SourceDocument = Join-Path $PSScriptRoot '..\docs\adaptive-launch-days-01-02.md'

if (-not (Test-Path -LiteralPath $TokenPath)) {
    throw "Todoist token file was not found: $TokenPath"
}

$apiToken = (Get-Content -Raw -LiteralPath $TokenPath).Trim()
if ([string]::IsNullOrWhiteSpace($apiToken)) {
    throw 'Todoist token file is empty.'
}

$headers = @{ Authorization = "Bearer $apiToken" }

function Invoke-TodoistGet {
    param([Parameter(Mandatory)][string]$Path)
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Method Get `
                -Uri "$ApiBase/$Path" -Headers $headers -TimeoutSec 30
            $json = [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray())
            return $json | ConvertFrom-Json
        } catch {
            if ($attempt -eq 6) { throw }
            Start-Sleep -Seconds ([math]::Min(20, [math]::Pow(2, $attempt)))
        }
    }
}

function Get-TodoistCollection {
    param([Parameter(Mandatory)][string]$Path)

    $items = @()
    $cursor = $null
    do {
        $separator = if ($Path.Contains('?')) { '&' } else { '?' }
        $uriPath = if ($cursor) {
            "$Path$separator" + 'cursor=' + [uri]::EscapeDataString($cursor)
        } else {
            $Path
        }
        $response = Invoke-TodoistGet -Path $uriPath
        if ($null -ne $response.results) {
            $items += @($response.results)
            $cursor = $response.next_cursor
        } else {
            $items += @($response)
            $cursor = $null
        }
    } while ($cursor)

    return @($items)
}

function Invoke-TodoistPost {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Payload
    )

    $json = $Payload | ConvertTo-Json -Depth 10 -Compress
    $body = [Text.Encoding]::UTF8.GetBytes($json)
    $postHeaders = @{
        Authorization = "Bearer $apiToken"
        'X-Request-Id' = [guid]::NewGuid().ToString()
    }
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Method Post `
                -Uri "$ApiBase/$Path" -Headers $postHeaders `
                -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 30
            $responseJson = [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray())
            return $responseJson | ConvertFrom-Json
        } catch {
            if ($attempt -eq 6) { throw }
            Start-Sleep -Seconds ([math]::Min(20, [math]::Pow(2, $attempt)))
        }
    }
}

function Invoke-TodoistDelete {
    param([Parameter(Mandatory)][string]$Path)
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Method Delete `
                -Uri "$ApiBase/$Path" -Headers $headers -TimeoutSec 30
            return $response.StatusCode
        } catch {
            if ($attempt -eq 6) { throw }
            Start-Sleep -Seconds ([math]::Min(20, [math]::Pow(2, $attempt)))
        }
    }
}

function Add-ManifestTask {
    param(
        [Parameter(Mandatory)][string]$Id,
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][string]$Section,
        [string]$DueDate,
        [string]$DueDateTime,
        [int]$Duration = 0,
        [int]$Priority = 1
    )

    if ($script:ManifestIds.ContainsKey($Id)) {
        throw "Duplicate manifest ID: $Id"
    }
    $script:ManifestIds[$Id] = $true
    $displayContent = if ($Duration -gt 0) { "$Content · $Duration мин" } else { $Content }
    $script:Manifest.Add([pscustomobject]@{
        Id = $Id
        Content = $displayContent
        Description = "[MP-ID:$Id]`n$Description"
        Section = $Section
        DueDate = $DueDate
        DueDateTime = $DueDateTime
        Duration = $Duration
        Priority = $Priority
    }) | Out-Null
}

function Get-MinutesBetween {
    param([string]$Start, [string]$End)
    $startTime = [datetime]::ParseExact($Start, 'HH:mm', $null)
    $endTime = [datetime]::ParseExact($End, 'HH:mm', $null)
    return [int]($endTime - $startTime).TotalMinutes
}

function Add-AdaptiveDayTable {
    param(
        [Parameter(Mandatory)][string]$Date,
        [Parameter(Mandatory)][string]$Prefix,
        [Parameter(Mandatory)][string]$SectionPattern,
        [Parameter(Mandatory)][string[]]$Titles
    )

    $document = Get-Content -Raw -Encoding utf8 -LiteralPath $SourceDocument
    $sectionText = [regex]::Match($document, $SectionPattern, 'Singleline').Value
    $rows = [regex]::Matches(
        $sectionText,
        '^\| (\d{2}:\d{2})–(\d{2}:\d{2}) \| (.*?) \| (.*?) \|$',
        'Multiline'
    )
    $workRows = @($rows | Where-Object {
        $_.Groups[3].Value -notmatch '^(Фаджр|Зухр) в мечети'
    })
    if ($workRows.Count -ne $Titles.Count) {
        throw "$Prefix table has $($workRows.Count) work rows; expected $($Titles.Count)."
    }

    for ($index = 0; $index -lt $workRows.Count; $index++) {
        $row = $workRows[$index]
        $start = $row.Groups[1].Value
        $end = $row.Groups[2].Value
        $childInstruction = $row.Groups[3].Value.Replace('`', '')
        $fatherInstruction = $row.Groups[4].Value.Replace('`', '')
        $section = if ($start -lt '08:15') { 'После Фаджра' } else { 'Утро до Зухра' }
        Add-ManifestTask -Id ('{0}-{1:D2}' -f $Prefix, ($index + 1)) `
            -Content $Titles[$index] `
            -Description "Ребенок: $childInstruction`nОтец: $fatherInstruction" `
            -Section $section `
            -DueDateTime "${Date}T${start}:00+03:00" `
            -Duration (Get-MinutesBetween -Start $start -End $end)
    }
}

function Add-FlexibleTask {
    param(
        [string]$Id,
        [string]$Date,
        [string]$Section,
        [string]$Content,
        [string]$Instruction,
        [int]$Duration
    )
    Add-ManifestTask -Id $Id -Content $Content -Description $Instruction `
        -Section $Section -DueDate $Date -Duration $Duration
}

function Add-FridayTask {
    param(
        [int]$Number,
        [string]$Start,
        [string]$End,
        [string]$Content,
        [string]$Instruction
    )
    Add-ManifestTask -Id ('MP-FRI-20260911-{0:D2}' -f $Number) -Content $Content `
        -Description $Instruction -Section 'Пятница' `
        -DueDateTime "2026-09-11T${Start}:00+03:00" `
        -Duration (Get-MinutesBetween -Start $Start -End $End)
}

$script:Manifest = [Collections.Generic.List[object]]::new()
$script:ManifestIds = @{}

# All five daily prayer blocks for the approved MVP period.
$prayerData = @'
2026-09-10,05:08,12:52,16:24,19:07,20:25
2026-09-11,05:09,12:52,16:23,19:06,20:24
2026-09-12,05:10,12:51,16:22,19:04,20:23
2026-09-13,05:10,12:51,16:22,19:03,20:21
2026-09-14,05:11,12:51,16:21,19:02,20:20
2026-09-15,05:12,12:50,16:20,19:01,20:19
2026-09-16,05:12,12:50,16:20,18:59,20:17
2026-09-17,05:13,12:50,16:19,18:58,20:16
2026-09-18,05:14,12:49,16:18,18:57,20:15
2026-09-19,05:14,12:49,16:17,18:56,20:13
2026-09-20,05:15,12:48,16:17,18:54,20:12
2026-09-21,05:16,12:48,16:16,18:53,20:11
2026-09-22,05:16,12:48,16:15,18:52,20:09
2026-09-23,05:17,12:47,16:14,18:51,20:08
2026-09-24,05:17,12:47,16:14,18:49,20:07
2026-09-25,05:18,12:47,16:13,18:48,20:05
2026-09-26,05:19,12:46,16:12,18:47,20:04
2026-09-27,05:19,12:46,16:11,18:46,20:03
2026-09-28,05:20,12:46,16:11,18:44,20:02
2026-09-29,05:21,12:45,16:10,18:43,20:00
2026-09-30,05:21,12:45,16:09,18:42,19:59
2026-10-01,05:22,12:45,16:08,18:41,19:58
2026-10-02,05:22,12:44,16:07,18:39,19:57
2026-10-03,05:23,12:44,16:07,18:38,19:55
2026-10-04,05:24,12:44,16:06,18:37,19:54
2026-10-05,05:24,12:43,16:05,18:36,19:53
2026-10-06,05:25,12:43,16:04,18:35,19:52
2026-10-07,05:25,12:43,16:03,18:33,19:51
2026-10-08,05:26,12:43,16:03,18:32,19:49
2026-10-09,05:27,12:42,16:02,18:31,19:48
'@ | ConvertFrom-Csv -Header Date,Fajr,Dhuhr,Asr,Maghrib,Isha

$prayers = @(
    @{ Key = 'FAJR'; Name = 'Фаджр'; Field = 'Fajr' },
    @{ Key = 'DHUHR'; Name = 'Зухр'; Field = 'Dhuhr' },
    @{ Key = 'ASR'; Name = 'Аср'; Field = 'Asr' },
    @{ Key = 'MAGHRIB'; Name = 'Магриб'; Field = 'Maghrib' },
    @{ Key = 'ISHA'; Name = 'Иша'; Field = 'Isha' }
)

foreach ($day in $prayerData) {
    foreach ($prayer in $prayers) {
        $start = $day.($prayer.Field)
        $end = ([datetime]::ParseExact($start, 'HH:mm', $null)).AddMinutes(40).ToString('HH:mm')
        $compactDate = $day.Date.Replace('-', '')
        Add-ManifestTask -Id "MP-SALAH-$compactDate-$($prayer.Key)" `
            -Content "$($prayer.Name) — мечеть и возвращение домой" `
            -Description "Начать точно во время азана. В блок входят подготовка, дорога, намаз в мечети и возвращение домой. Интервал: $start–$end. Источник времени: Sajda.com, Каир." `
            -Section 'Намазы' `
            -DueDateTime "$($day.Date)T${start}:00+03:00" `
            -Duration 40 -Priority 2
    }
}

$dayOneTitles = @(
    'Коран: прочитать знакомую короткую суру',
    'Умыться, одеться и заправить постель',
    'Завтрак',
    'Убрать посуду и стол',
    'Зарядка или активная игра',
    'Свободная игра без экрана',
    'Учусь работать по плану и ставить знак ?',
    'Перерыв без экрана',
    'Английский: стартовая проверка',
    'Duolingo ABC: первое простое занятие',
    'Свободная игра без экрана',
    'Перекус',
    'Программирование: порядок команд',
    'ScratchJr: первая программа',
    'Русский: прочитать и пересказать',
    'Русский: написать и проверить',
    'Свободная игра или рисование',
    'Убрать материалы и рабочее место',
    'Спокойное свободное время'
)
Add-AdaptiveDayTable -Date '2026-09-10' -Prefix 'MP-D1' `
    -SectionPattern '## День 1.*?(?=## Пятница)' -Titles $dayOneTitles

$dayTwoTitles = @(
    'Коран: повторить знакомую суру',
    'Умыться, одеться и заправить постель',
    'Завтрак',
    'Убрать посуду и стол',
    'Зарядка или активная игра',
    'Свободная игра без экрана',
    'Математика: стартовая проверка',
    'Khan Academy Kids: первое простое занятие',
    'Перерыв без экрана',
    'Арабский: стартовая проверка',
    'AlifBee: стартовое задание',
    'Свободная игра без экрана',
    'Перекус',
    'Инженерия: построить и проверить мост',
    'Инженерия: улучшить мост и объяснить',
    'Прочитать инструкцию и пересказать',
    'Lichess: первое знакомство с доской',
    'Свободная игра или рисование',
    'Убрать материалы и рабочее место',
    'Спокойное свободное время'
)
Add-AdaptiveDayTable -Date '2026-09-12' -Prefix 'MP-D2' `
    -SectionPattern '## День 2.*?(?=## Итоговая)' -Titles $dayTwoTitles

# Flexible tasks for the two adaptive days.
foreach ($dayInfo in @(
    @{ Date = '2026-09-10'; Prefix = 'MP-D1' },
    @{ Date = '2026-09-12'; Prefix = 'MP-D2' }
)) {
    $date = $dayInfo.Date
    $prefix = $dayInfo.Prefix
    Add-FlexibleTask "$prefix-Z-01" $date 'После Зухра' 'Обед' 'Поесть после возвращения с Зухра.' 30
    Add-FlexibleTask "$prefix-Z-02" $date 'После Зухра' 'Дневной сон' 'Спать до двух часов, завершить не позднее азана Асра.' 120
    Add-FlexibleTask "$prefix-A-01" $date 'После Асра' 'Разобрать вопросы со знаком ?' 'Вместе с отцом разобрать обычные вопросы; не более 15 минут.' 15
    Add-FlexibleTask "$prefix-A-02" $date 'После Асра' 'Прогулка или движение' 'Двигаться или гулять вместе со взрослым.' 45
    Add-FlexibleTask "$prefix-A-03" $date 'После Асра' 'Домашняя ответственность' 'Выполнить одну заранее выбранную безопасную домашнюю обязанность.' 15
    Add-FlexibleTask "$prefix-A-04" $date 'После Асра' 'Ранний ужин' 'Поужинать и убрать за собой.' 25
    Add-FlexibleTask "$prefix-M-01" $date 'После Магриба' 'Легкое повторение Корана' 'Повторение до 10 минут без новой сложной темы.' 10
    Add-FlexibleTask "$prefix-M-02" $date 'После Магриба' 'Спокойное семейное время' 'Спокойное общение без учебной нагрузки.' 20
    Add-FlexibleTask "$prefix-I-01" $date 'После Иша' 'Вечерняя гигиена' 'Подготовиться ко сну.' 15
    Add-FlexibleTask "$prefix-I-02" $date 'После Иша' 'Отметить выполненное и оставшиеся вопросы' 'Отметить сделанное и поставить знак ? там, где остался вопрос.' 5
    Add-FlexibleTask "$prefix-I-03" $date 'После Иша' 'Короткий отчет отцу' 'Назвать результат дня и одну трудность.' 10
}

# Light Friday between the two adaptive days.
$fridayTasks = @(
    @('05:49','06:09','Коран: знакомая короткая сура','Спокойно прочитать или повторить знакомую суру.'),
    @('06:09','06:31','Умыться, одеться и заправить постель','Выполнить утренний порядок.'),
    @('06:31','07:01','Завтрак','Позавтракать подготовленной едой.'),
    @('07:01','07:16','Убрать посуду и стол','Оставить после себя порядок.'),
    @('07:16','07:46','Зарядка или активная игра','Выбрать знакомое безопасное движение.'),
    @('07:46','09:16','Свободная игра без экрана','Разгрузочное свободное время.'),
    @('09:16','09:36','Легкое развивающее занятие','Одно простое занятие без диагностики и оценки.'),
    @('09:36','10:30','Свободная игра без экрана','Продолжить спокойную свободную игру.'),
    @('10:30','10:45','Перекус','Съесть подготовленный перекус.'),
    @('10:45','11:15','Рисование или конструктор','Выбрать одно спокойное творческое занятие.'),
    @('11:15','12:12','Свободная игра или семейное время','Без новой учебной нагрузки.'),
    @('12:12','12:32','Убрать материалы и рабочее место','Оставить после себя порядок.'),
    @('12:32','12:52','Спокойное время','Спокойно завершить утро до азана Зухра.')
)
for ($i = 0; $i -lt $fridayTasks.Count; $i++) {
    Add-FridayTask -Number ($i + 1) -Start $fridayTasks[$i][0] -End $fridayTasks[$i][1] `
        -Content $fridayTasks[$i][2] -Instruction $fridayTasks[$i][3]
}
Add-FlexibleTask 'MP-FRI-20260911-Z-01' '2026-09-11' 'Пятница' 'Обед после Зухра' 'Спокойный семейный обед.' 30
Add-FlexibleTask 'MP-FRI-20260911-Z-02' '2026-09-11' 'Пятница' 'Дневной сон' 'Отдых до двух часов, завершить не позднее азана Асра.' 120
Add-FlexibleTask 'MP-FRI-20260911-A-01' '2026-09-11' 'Пятница' 'Семейная прогулка' 'Прогулка или движение после Асра.' 45
Add-FlexibleTask 'MP-FRI-20260911-A-02' '2026-09-11' 'Пятница' 'Домашняя ответственность' 'Одна безопасная помощь семье.' 15
Add-FlexibleTask 'MP-FRI-20260911-A-03' '2026-09-11' 'Пятница' 'Ранний ужин' 'Поужинать и убрать за собой.' 25
Add-FlexibleTask 'MP-FRI-20260911-M-01' '2026-09-11' 'Пятница' 'Легкое повторение Корана' 'До 10 минут без новой сложной темы.' 10
Add-FlexibleTask 'MP-FRI-20260911-M-02' '2026-09-11' 'Пятница' 'Спокойное семейное время' 'Отдых без учебной нагрузки.' 20
Add-FlexibleTask 'MP-FRI-20260911-I-01' '2026-09-11' 'Пятница' 'Вечерняя гигиена' 'Подготовиться ко сну.' 15
Add-FlexibleTask 'MP-FRI-20260911-I-02' '2026-09-11' 'Пятница' 'Короткий отчет дня' 'Назвать одно сделанное дело и спокойно завершить день.' 10

# Parent-only setup and review tasks.
$parentTasks = @(
    @('MP-PARENT-01','2026-09-10T07:45:00+03:00',30,'Проверить iPadOS, Wi‑Fi и регион App Store','Проверить совместимость iPadOS. При необходимости запустить только официальное обновление.'),
    @('MP-PARENT-02','2026-09-10T08:40:00+03:00',20,'Установить Todoist, Tarteel и Duolingo ABC','Использовать немецкий App Store; не оформлять подписки и пробные периоды.'),
    @('MP-PARENT-03','2026-09-10T09:25:00+03:00',45,'Установить AlifBee, Khan Academy Kids, ScratchJr и Lichess','Создавать только необходимые аккаунты; пароли хранит отец.'),
    @('MP-PARENT-04','2026-09-10T11:40:00+03:00',20,'Проверить запуск семи приложений','Проверить оплату, разрешения, звук и доступ к микрофону; лишние разрешения отключить.'),
    @('MP-PARENT-05','2026-09-10T21:15:00+03:00',30,'Заполнить результаты адаптационного дня 1','Зафиксировать уровни помощи, экранное время и технические проблемы.'),
    @('MP-PARENT-06','2026-09-12T07:47:00+03:00',30,'Подготовить математику и приложения ко дню 2','Подготовить лист, карандаш и открыть Khan Academy Kids и AlifBee.'),
    @('MP-PARENT-07','2026-09-12T09:27:00+03:00',45,'Подготовить безопасный конструктор','Подготовить две опоры и небольшой безопасный груз для проверки моста.'),
    @('MP-PARENT-08','2026-09-12T21:15:00+03:00',30,'Заполнить итоговую таблицу двух дней','Поставить уровни 0–3 и записать следующий базовый шаг по каждому направлению.'),
    @('MP-PARENT-09','2026-09-12T21:45:00+03:00',15,'Контрольная точка: подготовить результаты для следующего плана','Ответить на четыре итоговых вопроса и не повышать нагрузку до корректировки программы.')
)
foreach ($item in $parentTasks) {
    $targetSection = if ($item[0] -in @('MP-PARENT-05', 'MP-PARENT-08', 'MP-PARENT-09')) {
        'Проверка и результаты'
    } else {
        'Запуск системы — отец'
    }
    Add-ManifestTask -Id $item[0] -Content "Отец: $($item[3])" -Description $item[4] `
        -Section $targetSection -DueDateTime $item[1] -Duration $item[2] -Priority 2
}

Add-ManifestTask -Id 'MP-PARENT-FRIDAY' -Content 'Отец: завершить техническую настройку без участия ребенка' `
    -Description 'Если обновление iPadOS или загрузка приложений не завершились 10 сентября, закончить их в пятницу. Не добавлять ребенку новую диагностику.' `
    -Section 'Запуск системы — отец' -DueDate '2026-09-11' -Duration 30

$sectionNames = @(
    'Запуск системы — отец',
    'Намазы',
    'После Фаджра',
    'Утро до Зухра',
    'После Зухра',
    'После Асра',
    'После Магриба',
    'После Иша',
    'Пятница',
    'Проверка и результаты'
)

if ($DryRun) {
    [pscustomobject]@{
        ProjectName = $ProjectName
        Sections = $sectionNames.Count
        Tasks = $script:Manifest.Count
        PrayerTasks = @($script:Manifest | Where-Object { $_.Id -like 'MP-SALAH-*' }).Count
        TimedTasks = @($script:Manifest | Where-Object { $_.DueDateTime }).Count
        FlexibleTasks = @($script:Manifest | Where-Object { $_.DueDate }).Count
        UniqueIds = $script:ManifestIds.Count
    } | Format-List
    $script:Manifest | Group-Object Section | Sort-Object Name | Select-Object Name,Count | Format-Table -AutoSize
    return
}

# Reuse only an exact-name project. Existing unrelated projects stay untouched.
$projects = Get-TodoistCollection -Path 'projects'
$project = @($projects | Where-Object { $_.name -eq $ProjectName -and -not $_.is_archived })
if ($project.Count -gt 1) {
    throw "More than one active Todoist project is named '$ProjectName'."
}
if ($project.Count -eq 0) {
    $project = Invoke-TodoistPost -Path 'projects' -Payload @{ name = $ProjectName }
    Write-Output "Created project: $ProjectName ($($project.id))"
} else {
    $project = $project[0]
    Write-Output "Using existing project: $ProjectName ($($project.id))"
}

$sections = Get-TodoistCollection -Path 'sections'
$projectSections = @($sections | Where-Object { $_.project_id -eq $project.id })
$sectionIds = @{}
foreach ($sectionName in $sectionNames) {
    $matches = @($projectSections | Where-Object { $_.name -eq $sectionName })
    if ($matches.Count -gt 1) {
        throw "Duplicate section '$sectionName' in project '$ProjectName'."
    }
    if ($matches.Count -eq 0) {
        $createdSection = Invoke-TodoistPost -Path 'sections' -Payload @{
            name = $sectionName
            project_id = $project.id
        }
        $sectionIds[$sectionName] = $createdSection.id
        Write-Output "Created section: $sectionName"
    } else {
        $sectionIds[$sectionName] = $matches[0].id
    }
}

$allTasks = Get-TodoistCollection -Path 'tasks'
$existingProjectTasks = @($allTasks | Where-Object { $_.project_id -eq $project.id })
$existingIds = @{}
$duplicateTaskIds = [Collections.Generic.List[string]]::new()
foreach ($task in $existingProjectTasks) {
    $marker = [regex]::Match([string]$task.description, '\[MP-ID:([^\]]+)\]')
    if ($marker.Success) {
        $markerId = $marker.Groups[1].Value
        if ($existingIds.ContainsKey($markerId)) {
            $kept = $existingIds[$markerId]
            $keptFingerprint = @(
                $kept.content,
                $kept.description,
                $kept.section_id,
                $kept.due.date,
                $kept.duration.amount,
                $kept.duration.unit
            ) -join "`n"
            $duplicateFingerprint = @(
                $task.content,
                $task.description,
                $task.section_id,
                $task.due.date,
                $task.duration.amount,
                $task.duration.unit
            ) -join "`n"
            if ($keptFingerprint -ne $duplicateFingerprint) {
                throw "Tasks with marker $markerId are not exact duplicates; refusing cleanup."
            }
            $duplicateTaskIds.Add([string]$task.id) | Out-Null
        } else {
            $existingIds[$markerId] = $task
        }
    }
}

if ($duplicateTaskIds.Count -gt 0) {
    Write-Output "Removing exact duplicate tasks created by interrupted synchronization: $($duplicateTaskIds.Count)"
    Add-Type -AssemblyName System.Net.Http
    $deleteClient = [Net.Http.HttpClient]::new()
    $deleteClient.DefaultRequestHeaders.Authorization = `
        [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $apiToken)
    $deleteArray = @($duplicateTaskIds.ToArray())
    try {
        for ($deleteStart = 0; $deleteStart -lt $deleteArray.Count; $deleteStart += 20) {
            $deleteEnd = [math]::Min($deleteStart + 19, $deleteArray.Count - 1)
            $deletePending = [Collections.Generic.List[object]]::new()
            foreach ($deleteIndex in @($deleteStart..$deleteEnd)) {
                $taskId = $deleteArray[$deleteIndex]
                $request = [Net.Http.HttpRequestMessage]::new(
                    [Net.Http.HttpMethod]::Delete,
                    "$ApiBase/tasks/$taskId"
                )
                $deletePending.Add([pscustomobject]@{
                    Id = $taskId
                    Request = $request
                    Promise = $deleteClient.SendAsync($request)
                }) | Out-Null
            }
            [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($deletePending.Promise))
            foreach ($item in $deletePending) {
                $response = $item.Promise.Result
                if (-not $response.IsSuccessStatusCode) {
                    $errorBody = $response.Content.ReadAsStringAsync().Result
                    throw "Duplicate cleanup failed for $($item.Id): $([int]$response.StatusCode) $errorBody"
                }
                $response.Dispose()
                $item.Request.Dispose()
            }
            Write-Output "Removed duplicates: $($deleteEnd + 1) / $($deleteArray.Count)"
        }
    } finally {
        $deleteClient.Dispose()
    }
    Write-Output 'Exact duplicate cleanup completed.'
}

$createdCount = 0
$skippedCount = 0
$tasksToCreate = [Collections.Generic.List[object]]::new()
foreach ($task in $script:Manifest) {
    if ($existingIds.ContainsKey($task.Id)) {
        $skippedCount++
    } else {
        $tasksToCreate.Add($task) | Out-Null
    }
}

# Task creation is parallelized in modest batches to keep a large approved plan
# within one API session. Existing marker checks above keep reruns idempotent.
Add-Type -AssemblyName System.Net.Http
$httpClient = [Net.Http.HttpClient]::new()
$httpClient.DefaultRequestHeaders.Authorization = `
    [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $apiToken)
$batchSize = 10
$taskArray = @($tasksToCreate.ToArray())
try {
    for ($batchStart = 0; $batchStart -lt $taskArray.Count; $batchStart += $batchSize) {
        $batchEnd = [math]::Min($batchStart + $batchSize - 1, $taskArray.Count - 1)
        $pending = [Collections.Generic.List[object]]::new()
        $batchIndexes = @($batchStart..$batchEnd)
        foreach ($taskIndex in $batchIndexes) {
            $task = $taskArray[$taskIndex]
            $payload = @{
                content = $task.Content
                description = $task.Description
                project_id = $project.id
                section_id = $sectionIds[$task.Section]
                priority = $task.Priority
            }
            if ($task.DueDateTime) {
                $payload.due_datetime = $task.DueDateTime
            } elseif ($task.DueDate) {
                $payload.due_date = $task.DueDate
            }
            if ($task.Duration -gt 0) {
                $payload.duration = $task.Duration
                $payload.duration_unit = 'minute'
            }
            $bodyBytes = [Text.Encoding]::UTF8.GetBytes(
                ($payload | ConvertTo-Json -Depth 10 -Compress)
            )
            $request = [Net.Http.HttpRequestMessage]::new(
                [Net.Http.HttpMethod]::Post,
                "$ApiBase/tasks"
            )
            $request.Headers.Add('X-Request-Id', [guid]::NewGuid().ToString())
            $request.Content = [Net.Http.ByteArrayContent]::new($bodyBytes)
            $request.Content.Headers.ContentType = `
                [Net.Http.Headers.MediaTypeHeaderValue]::Parse('application/json; charset=utf-8')
            $pending.Add([pscustomobject]@{
                Id = $task.Id
                Request = $request
                Promise = $httpClient.SendAsync($request)
            }) | Out-Null
        }

        [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($pending.Promise))
        foreach ($item in $pending) {
            $response = $item.Promise.Result
            if (-not $response.IsSuccessStatusCode) {
                $errorBody = $response.Content.ReadAsStringAsync().Result
                throw "Todoist task $($item.Id) failed: $([int]$response.StatusCode) $errorBody"
            }
            $createdCount++
            $response.Dispose()
            $item.Request.Dispose()
        }
        Write-Output "Created tasks this run: $createdCount / $($taskArray.Count); already existed: $skippedCount"
    }
} finally {
    $httpClient.Dispose()
}

# The Todoist Free plan may ignore the native duration field. Keep duration in
# the visible task title in every plan, and bring previously created titles in
# line with the manifest without changing dates, sections, or descriptions.
$tasksToUpdate = [Collections.Generic.List[object]]::new()
foreach ($manifestTask in $script:Manifest) {
    if ($existingIds.ContainsKey($manifestTask.Id)) {
        $remoteTask = $existingIds[$manifestTask.Id]
        if ($remoteTask.content -ne $manifestTask.Content) {
            $tasksToUpdate.Add([pscustomobject]@{
                Id = $manifestTask.Id
                TaskId = $remoteTask.id
                Content = $manifestTask.Content
            }) | Out-Null
        }
    }
}

if ($tasksToUpdate.Count -gt 0) {
    $updateClient = [Net.Http.HttpClient]::new()
    $updateClient.DefaultRequestHeaders.Authorization = `
        [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $apiToken)
    $updateArray = @($tasksToUpdate.ToArray())
    try {
        for ($updateStart = 0; $updateStart -lt $updateArray.Count; $updateStart += 20) {
            $updateEnd = [math]::Min($updateStart + 19, $updateArray.Count - 1)
            $updatePending = [Collections.Generic.List[object]]::new()
            foreach ($updateIndex in @($updateStart..$updateEnd)) {
                $item = $updateArray[$updateIndex]
                $bodyBytes = [Text.Encoding]::UTF8.GetBytes(
                    (@{ content = $item.Content } | ConvertTo-Json -Compress)
                )
                $request = [Net.Http.HttpRequestMessage]::new(
                    [Net.Http.HttpMethod]::Post,
                    "$ApiBase/tasks/$($item.TaskId)"
                )
                $request.Headers.Add('X-Request-Id', [guid]::NewGuid().ToString())
                $request.Content = [Net.Http.ByteArrayContent]::new($bodyBytes)
                $request.Content.Headers.ContentType = `
                    [Net.Http.Headers.MediaTypeHeaderValue]::Parse('application/json; charset=utf-8')
                $updatePending.Add([pscustomobject]@{
                    Id = $item.Id
                    Request = $request
                    Promise = $updateClient.SendAsync($request)
                }) | Out-Null
            }
            [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($updatePending.Promise))
            foreach ($pendingUpdate in $updatePending) {
                $response = $pendingUpdate.Promise.Result
                if (-not $response.IsSuccessStatusCode) {
                    $errorBody = $response.Content.ReadAsStringAsync().Result
                    throw "Todoist update $($pendingUpdate.Id) failed: $([int]$response.StatusCode) $errorBody"
                }
                $response.Dispose()
                $pendingUpdate.Request.Dispose()
            }
            Write-Output "Updated visible durations: $($updateEnd + 1) / $($updateArray.Count)"
        }
    } finally {
        $updateClient.Dispose()
    }
}

# Read everything back and verify deterministic markers and prayer fields.
$verifiedTasks = Get-TodoistCollection -Path 'tasks'
$verifiedProjectTasks = @($verifiedTasks | Where-Object { $_.project_id -eq $project.id })
$verifiedById = @{}
foreach ($task in $verifiedProjectTasks) {
    $marker = [regex]::Match([string]$task.description, '\[MP-ID:([^\]]+)\]')
    if ($marker.Success) {
        if ($verifiedById.ContainsKey($marker.Groups[1].Value)) {
            throw "Duplicate Todoist marker: $($marker.Groups[1].Value)"
        }
        $verifiedById[$marker.Groups[1].Value] = $task
    }
}

$missingIds = @($script:Manifest | Where-Object { -not $verifiedById.ContainsKey($_.Id) } | ForEach-Object { $_.Id })
if ($missingIds.Count -gt 0) {
    throw "Missing tasks after synchronization: $($missingIds -join ', ')"
}

$prayerErrors = @()
foreach ($manifestTask in @($script:Manifest | Where-Object { $_.Id -like 'MP-SALAH-*' })) {
    $remoteTask = $verifiedById[$manifestTask.Id]
    $nativeDurationIsCorrect = (
        $null -ne $remoteTask.duration -and
        [int]$remoteTask.duration.amount -eq 40 -and
        $remoteTask.duration.unit -eq 'minute'
    )
    $visibleDurationIsCorrect = $remoteTask.content -match ' · 40 мин$'
    if (-not $nativeDurationIsCorrect -and -not $visibleDurationIsCorrect) {
        $prayerErrors += "$($manifestTask.Id): duration"
    }
    if (-not $remoteTask.due.date) {
        $prayerErrors += "$($manifestTask.Id): due date/time"
    }
}
if ($prayerErrors.Count -gt 0) {
    throw "Prayer verification failed: $($prayerErrors -join '; ')"
}

$verifiedSections = Get-TodoistCollection -Path 'sections'
$verifiedSectionNames = @($verifiedSections | Where-Object { $_.project_id -eq $project.id } | ForEach-Object { $_.name })
$missingSections = @($sectionNames | Where-Object { $_ -notin $verifiedSectionNames })
if ($missingSections.Count -gt 0) {
    throw "Missing sections after synchronization: $($missingSections -join ', ')"
}

[pscustomobject]@{
    ProjectId = $project.id
    ProjectName = $ProjectName
    ExpectedSections = $sectionNames.Count
    VerifiedSections = $verifiedSectionNames.Count
    ManifestTasks = $script:Manifest.Count
    CreatedTasks = $createdCount
    SkippedExistingTasks = $skippedCount
    VerifiedMarkedTasks = $verifiedById.Count
    PrayerTasks = @($script:Manifest | Where-Object { $_.Id -like 'MP-SALAH-*' }).Count
} | Format-List
