# mimotion

![ 刷步数](https://github.com/TonyJiangWJ/mimotion/actions/workflows/run.yml/badge.svg)
[![GitHub forks](https://img.shields.io/github/forks/TonyJiangWJ/mimotion?style=flat-square)](https://github.com/TonyJiangWJ/mimotion/forks)
[![GitHub stars](https://img.shields.io/github/stars/TonyJiangWJ/mimotion?style=flat-square)](https://github.com/TonyJiangWJ/mimotion/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/TonyJiangWJ/mimotion?style=flat-square)](https://github.com/TonyJiangWJ/mimotion/issues)

## 小米运动自动刷步数（支持邮箱登录）

- 小米运动自动刷步数，小米运动APP现已改名 `Zepp Life`，为方便说明，后面还是称其为小米运动。但下载注册时请搜索 `Zepp Life`。
- 注册账号后建议先去以下网站测试自己的账号刷步数是否正常（注意这些网站只是网络上收集的，不保证安全和有效性）：
    - https://steps.hubp.de/ 提示密码错误时可以多试几次 或者切换网络
    - https://bs.yanwan.store/run4/ 验证码001或998
- 如无法刷步数同步到支付宝等，建议重新注册一个新的。

## 新注册账号使用方法

由于新注册账号没有绑定过手环，会导致华米拦截向微信同步步数，此时你需要做的就是绑定一次小米1-7代任意手环即可。如果没有可以参考以下步骤：
- 前往 `https://bs.yanwan.store/run4/` 网站执行一次步数同步
- 该网站会自动为你账号绑定一个虚拟设备（感谢该建站大佬）
- 你可以在你 Zepp Life 中看到这个虚拟的设备
- 然后按照以下步骤进行配置即可成功同步了

### 上传成功但微信步数未更新

- 网站和本脚本提交的是**当日总步数**，不是在实际步数上追加。例如今天已有2013步，再提交892或1501步属于较低的总数，不能据此判断微信同步失败。登录网站后的“提交修改”也会写入填写的当日总数。
- 本脚本上传前读取北京时间当天的华米云端步数，目标值不高于云端总数或当天最近一次成功上传值时跳过上传，避免重复运行造成回退；读取失败或记录格式异常时停止上传。保护范围为华米云端和本脚本保存的记录，不包括手机尚未上传的实际步数，也无法阻止其他网站覆盖记录。
- 日志中的 `已跳过上传` 表示保留已有总数；配置的 `MIN_STEP`/`MAX_STEP` 仍表示每日目标总数，按当天时间比例折算，不表示额外增加的步数。上传和跳过都不能验证微信实际显示。
- 在 Actions 手动运行“刷步数”时，可填写 `target_step` 指定本次的当日目标总数（例如3000），该值不按时间折算，仍受防回退保护。留空或定时执行沿用原有配置范围；本地运行可使用环境变量 `TARGET_STEP`，均不会修改已保存的配置。
- 首次登录后，程序会将登录接口返回的用户ID用于查询绑定设备和上传步数；后续运行会复用加密保存的用户ID，并在每次上传前重新确认云端绑定设备，避免换设备后使用旧设备ID。
- 日志出现 `查找到已绑定设备ID` 时，上传请求中的设备ID会使用查询到的值。
- 设备查询使用 `lists.json` 的 `data` 列表，兼容 `type`/`deviceType`/`device_type` 和 `deviceId`/`deviceid`/`macAddress`/`mac` 字段；类型为0的设备不依赖名称是否包含手环或手表关键词。
- 日志中的 HTTP 错误、接口错误或格式异常表示查询失败，不等同于账号没有绑定设备。查询失败时会停止该账号上传，并保留原缓存以供下次重试。
- 日志出现 `未查询到绑定设备，回退到默认设备ID` 时，程序保留旧账号的兼容逻辑，但不能保证微信同步。请先在 Zepp Life 中确认该账号已绑定设备，并已关联目标微信账号。
- `修改步数（…）[success]` 只表示华米上传接口接受了请求，不是微信同步成功的确认；请以微信运动实际显示为准。

### 如果觉得好用，请给一个免费的[star](https://github.com/TonyJiangWJ/mimotion/)吧

## Github Actions 部署指南

### 一、Fork 此仓库，然后创建token

#### 创建小权限的限时token，推荐

- 前往[https://github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta)
  创建个人token，建议使用Fine-grained tokens，避免token泄露导致不必要的麻烦。
- 填写token的名称，用于自己区别干嘛用的。
- 选择token有效期，最大时长为1年。一年后需要重新续期或重建，唯一缺点
- `Repository access` 选择 `Only select repositories` 勾选自己fork后的仓库，下拉可搜索：输入 mimotion 进行检索
- 点击 `Repository permissions` 展开菜单，并勾选以下四个权限即可，其他的可以不勾选
    - `Actions` Access: `Read and write` 用于获取Actions的权限
    - `Contents` Access: `Read and write` 用于更新定时任务和日志文件的权限
    - `Metadata` Access: `Read-only` 这个自带的必选
    - `Workflows` Access: `Read and write` 获取用于更新 `.github/workflow` 下文件的权限

#### 你也可以创建更大权限的不限时token

- 建议使用上面的小权限token，这个token无法指定某一个仓库的权限，也就是token一旦泄露将有可能导致其他人直接自由访问和修改你的所有仓库代码
- 前往[https://github.com/settings/tokens/new](https://github.com/settings/tokens/new)创建
- 填写token名称，选择有效期
- `Select scopes` 勾选 `repo` 和 `workflow` 即可

#### 创建完毕后点击最底下的 `Generate token` 即可生成token，复制token并自己保存一下以备后续使用，关闭当前页面后将无法再看到它。

### 二、设置账号密码

#### 前往仓库设置创建变量

- Settings-->Secrets and variables-->Actions-->New repository secret
-
快捷跳转地址 [https://github.com/${你的github用户名}/mimotion/settings/secrets/actions](../../settings/secrets/actions)
- 点击右侧的 `New repository secret` 即可添加Secret

#### 添加名为 **PAT** 的Secret变量，值为第一步申请的token

- `PAT` 的作用是拿来更新随机执行时间以及加密token数据的，为了保证正常使用，一定要配置正确。

#### 添加名为 **AES_KEY** 的Secret变量，请自行创建一个长度为16个字符的字符串作为密钥

- 注意：密钥不要用中文，长度一定要是16个字符，否则可能出错。
- 如果你有多个账号，或者希望程序自动保存登录信息，就需要设置这个 `AES_KEY`。设置之后，程序会用这个密钥把各个账号的登录token信息加密保存起来。**请一定保管好你的密钥，不要泄露。**
- 本地凭据缓存使用带完整性校验的 AES-GCM。旧版 AES-CBC 缓存可直接读取，下次保存会自动迁移；迁移后的文件不能用旧版程序读取。登录接口所需的 CBC 加密协议不受影响。
- 本地保存采用原子替换，并通过进程锁阻止多个程序同时修改缓存。
- 同时，请确保你已经正确配置了 PAT 密钥，否则程序无法自动保存和提交信息到仓库。未配置或无效的 AES_KEY 会禁用保存功能；工作流没有凭据变更时正常跳过提交。
- 第一次配置 `AES_KEY` 后，运行时可能会看到提示：“密钥不正确或者加密内容损坏 放弃token”，**这是正常现象**。因为原来加密文件用的是我的密钥，和你设置的不同，所以会提示不匹配。你直接忽略它，等程序运行完后，就会用你的新密钥生成一份新的加密文件，下次运行就正常了。
- 配置 `AES_KEY` 后，每个人的仓库里面到会保存一份 `encrypted_tokens.data`。每次更新代码时，这个文件会被覆盖。**为了避免丢失你保存的信息，请在更新代码前备份这个文件**，等代码更新完，再把它放回仓库并提交，最后重新运行workflow。

#### 添加名为 **CONFIG** 的Secret变量

- 需要注意Secret变量是密文，提交后无法查看，只能删除或用新值更新，建议本地保存一下自己的配置数据方便后期修改。或者参考步骤八导出配置数据。
- CONFIG的内容：

  ```json
  {
    "USER": "abcxxx@xx.com",
    "PWD": "password",
    "MIN_STEP": "18000",
    "MAX_STEP": "25000",
    "PUSH_PLUS_TOKEN": "",
    "PUSH_PLUS_HOUR": "",
    "PUSH_PLUS_MAX": "30",
    "PUSH_WECHAT_WEBHOOK_KEY": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "SLEEP_GAP": "5",
    "USE_CONCURRENT": "False"
  }
  ```

  | 字段名                     | 格式                                                                                                             |
  |-------------------------|----------------------------------------------------------------------------------------------------------------|
  | USER                    | 小米运动登录账号，仅支持小米运动账号对应的手机号或邮箱，不支持小米账号                                                                            |
  | PWD                     | 小米运动登录密码，仅支持小米运动账号对应的密码                                                                                        |
  | MIN_STEP                | 最小步数                                                                                                           |
  | MAX_STEP                | 最大步数，最大步数和最小步数随机范围随着时间线性增加，北京时间22点达到最大值                                                                        |
  | PUSH_PLUS_TOKEN         | 推送加的个人token,申请地址[pushplus](https://www.pushplus.plus/push1.html)，工作流执行完成后推送每个账号的执行状态信息，如没有则不要填写                |
  | PUSH_PLUS_HOUR          | 限制只在某个整点进行pushplus的推送，值为整数，比如设置21，则只在北京时间21点XX分执行时才进行pushplus的消息推送。如不设置、值非数字或不在0-23范围则每次执行后都会进行推送；仅影响PushPlus，企业微信和Telegram不受此字段限制                       |
  | PUSH_WECHAT_WEBHOOK_KEY | 企业微信推送通知的key，企业微信webhook机器人推送全地址为：https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={机器人的key}，这里配置{机器人的key} |
  | PUSH_PLUS_MAX           | 设置pushplus最大推送账号详情数，默认为30，超过30个账号将只推送概要信息：多少个成功多少个失败。因为数量太多会导致内容过长无法推送。具体最大值请自行调试                              |
  | TELEGRAM_BOT_TOKEN      | 设置telegram机器人的token，同时需要配置TELEGRAM_CHAT_ID，否则不会执行推送                                                            |
  | TELEGRAM_CHAT_ID        | 设置telegram的chatId，需要同时配置TELEGRAM_BOT_TOKEN，否则无法执行推送。关于这两个值如何获取，请前往官网查看。                                        |
  | SLEEP_GAP               | 多账号执行间隔，单位秒，如果账号比较多可以设置的短一点，默认为5秒                                                                              |
  | USE_CONCURRENT          | 是否使用多线程，支持字符串 `True`/`False` 或JSON布尔值 `true`/`false`；启用后 `SLEEP_GAP` 将不再生效                                               |

### 三、多账户设置(如用不上请忽略)

- 多账户请用 **#** 分割 然后保存到变量 **USER** 和 **PWD**
- 理论上账户数量不受限制，但是实际要看github actions的资源和华米接口是否有限制，pushplus消息内容应该也有最大长度限制，反正具体上限请自行测试

#### 例如

```json
{
  "USER": "13800138000#13800138001",
  "PWD": "abc123qwe#abcqwe2",
  "MIN_STEP": "18000",
  "MAX_STEP": "25000",
  "PUSH_PLUS_TOKEN": "",
  "PUSH_PLUS_HOUR": ""
}
```

#### 注意 **#** 分隔的账号和密码数量必须匹配，否则将跳过执行

### 四、自定义启动时间

#### 两种方式自定义启动时间

##### 1、添加名为 `CRON_HOURS` 的Variables变量 `Settings-->Secrets and variables-->Actions-->New repository variables` 注意不是Secret

-
快捷跳转地址 [https://github.com/${你的github用户名}/mimotion/settings/variables/actions](../../settings/variables/actions)
    - 填写自动执行的时间，单位为小时，此处需要设置UTC时间，例如设置 `0,2,4,6,8,14` 则会在北京时间 `8,10,12,14,16,22` 点触发执行
- 添加完成后可以在Actions中手动触发：`Random Cron` 来触发替换，或者等下一次定时执行时它将会自动替换。

##### 2、编辑 **.github/workflows/run.yml** 中的cron表达式

- cron表达式格式如下: `分 小时 日 月 星期`
- github actions中执行时间为UTC时间，即**北京时间-8**，如果需要每天`8，10，12，14，16，22`
  点执行，则设置cron为`0 0,2,4,6,8,14 * * *`

  ```yaml
  on:
    schedule:
      - cron: '0 0,2,4,6,8,14 * * *'
  ```

- **注意** 如果已添加 `CRON_HOURS` 变量，则修改此文件的cron表达式会失效，在下次执行 `Random Cron`
  后表达式中小时的部分会被覆盖为 `CRON_HOURS` 配置的值

- 注意以上两种方式二选一即可，推荐直接使用方式1，变量值填写的是逗号分隔的数字，别乱填别的报错别找我！
- github actions 0点为执行高峰，排队可能会延后一两小时才执行，建议直接从2开始

### 五、手动触发测试工作流

- 前往Actions,左侧选择 `刷步数`
  ，快捷链接：[https://github.com/${你的github用户名}/mimotion/actions/workflows/run.yml](../../actions/workflows/run.yml)
- 新fork的仓库默认未启用工作流，进入Actions后点击 `I understand my workflows, go ahead and enable them`
  启用，然后左侧选择 `刷步数` 之后，再点击 `enable workflow` 启用工作流。请确保开启工作流，否则不会定时执行。
- 点击右侧的`Run workflow`触发执行，触发后刷新即可查看执行记录。验证是否正确配置并执行刷步数。

### 六、感谢列表

本项目基于 `https://github.com/xunichanghuan/mimotion(已被ban)`
和 [https://github.com/huangshihai/mimotion](https://github.com/huangshihai/mimotion) 项目修改，特此感谢

新版本登录需要加密，感谢[https://github.com/hanximeng/Zepp_API/blob/main/index.php](https://github.com/hanximeng/Zepp_API/blob/main/index.php)
里面提供的aes加密密钥。大家可以去给作者点个star

### 七、同步最新代码

- 点击仓库界面上的 `Sync fork`，找不到的话直接Ctrl+F网页查找
- 然后点击 `Update branch` 或者 `Discard xxx commits`等待同步完成即可，如有其他提示请自行按提示操作。请不要提交 **pull request**
- 当配置了 `AES_KEY` 之后，因为每个人的仓库里面到会保存一份 `encrypted_tokens.data`，更新代码会被覆盖。为了避免数据丢失，请提前备份，在更新完成后将它重新提交到仓库中，然后再触发workflow。
- 同步更新后请自己再次仔细阅读README，配置项目修改等请自行对比，更新后因为配置不正确导致无法运行请不要找我

### 八、忘记配置后的处理

- 当长时间没有使用或者忘记了配置，可以通过手动触发工作流来发送配置信息到企业微信通知中，或者telegram机器人，请务必配置在私有的企业微信或telegram群组中，避免密码等敏感信息泄露给别人
- 步骤：
  - 首先配置Secrets：`INSPECT_WECHAT_HOOK_KEY` 配置企业微信机器人的key，具体请参考企业微信机器人文档。
  - telegram配置Secrets：`INSPECT_TELEGRAM_BOT_TOKEN`和`INSPECT_TELEGRAM_CHAT_ID` 配置机器人的token和聊天chatId，具体请参考TelegramBot文档。
  - 然后点击Actions，左侧选择 `提取配置信息` 手动运行它，运行成功后，将配置信息发送到企业微信或telegram中。企业微信或者telegram的推送自己按需选择，如果都不配置，请使用日志打印的方式。
- 如果没有企业微信或telegram，可以配置Secrets: `INSPECT_AES_KEY` 注意是16位的字符串，请勿使用弱密码，避免被人猜到。
  - 在Secrets中配置后，运行上述的Actions，然后在执行结果中查看日志打印的base64字符串。
  - 提取base64字符串后，可以使用在线AES加解密网站进行解密，加密方式为CBC，填充方式为PKCS7，密钥长度128bit，密钥和偏移量（iv）均为INSPECT_AES_KEY
  - 可用网站：https://www.toolhelper.cn/SymmetricEncryption/AES
- 以上两种方式都可以提取 CONFIG，PAT，AES_KEY 三个Secrets配置，请自行选择。

## 注意事项

1. 当前默认在北京时间20、21、22、23点运行，由run.yml中的cron控制；Random Cron成功执行后更新随机分钟值。随机后可能当前整点二次执行，例如：8:
   05分执行后，分钟值随机为50，则会在8:50再次执行。

- 如果配置了 `CRON_HOURS` Variable变量，则脚本将自动判断，例如8:05分执行后，将从小时中剔除8，即8:00-8:59都不会再重复执行，避免随机的步数混乱。

2. 多账户的数量和密码请一定要对上 不然无法使用!!!

3. 启动时间得是UTC时间!

4. 如果支付宝没有更新步数，到小米运动->设置->账号->注销账号->清空数据，然后重新登录，重新绑定第三方。建议去开头提到的网站测试账号是否正常

5. 小米运动不会更新步数，只有关联的会同步！！！！！

6. 请各位在使用时Fork[当前仓库](https://github.com/TonyJiangWJ/mimotion/)，防止出现不必要的bug.

7. 请注意，账号不是 [小米账号]，而是 [小米运动/ZeppLife] 的账号。

8. 最大步数和最小步数随着时间增长，10点执行时范围为10/22 \* 18000 ~ 10/22 \* 25000：8181 ~
   11363，以此类推，在北京时间22点达到最大值，即22点执行时随机步数的范围为18000-25000之间。要修改这个范围可以修改CONFIG中的MIN_STEP和MAX_STEP。

9. cron的执行根据github actions的资源进行排队，并不是百分百按指定的时间进行运行，请知悉。

10. 新版本接口有限制，同ip登录过多账号可能会429，请自行测试。

### 查看执行记录

- 前往 [Actions](../../actions) 可以查看所有工作流的执行历史
    - `刷步数 #41: Scheduled` 代表是定时任务触发，`刷步数 #33: Manually run by xxx` 代表手动触发
- 点击其中一条记录，可以查看执行详情，这里以 `刷步数` 为例：
    - 详情界面 `Jobs` 可以查看到一个 `build` ，点击它查看执行步骤
    - 执行步骤中主要关注 `开始` ，点击 `开始` 展开详情
    - 展开后便可以查看到执行日志，如果执行成功，则会显示每个账号当前随机的步数是多少
    - 如果执行失败，则需要根据实际情况分析具体失败原因
- 对于随机Cron的工作流 `Random Cron`，它会在 `刷步数` 执行成功后触发，执行后会更新cron表达式创建随机的分钟值，然后提交到git仓库。这一步失败的主要原因有：
    - `PAT` Secret变量，也就是个人token设置的不正确
    - `CRON_HOURS` Variable变量设置的不正确，需要逗号分隔的小时字符串例如：`1,3,4,5,6,7` 。小时必须为0-23，程序会排序去重并拒绝非法格式
    - 其他请见执行日志
- 随机Cron运行完毕后可以查看 `cron_change_time` 文件的内容，记录了触发方式、当前触发时间、cron表达式信息、下一次定时触发时间等信息，示例如下：
  ```log
  trigger by: workflow_run
  current system time:
  UTC: 23-06-03 12:56:53
  北京时间: 23-06-03 20:56:53
  current cron:
  UTC时间: '48 1,4,7,10,12,14 * * *'
  北京时间: '48 9,12,15,18,20,22 * * *'
  next cron:
  UTC时间: '37 1,4,7,10,12,14 * * *'
  北京时间: '37 9,12,15,18,20,22 * * *'
  next exec time: UTC(14:37) 北京时间(22:37)
  ```

## 本地开发

复制 `.env.example` 文件为 `.env`，并在 `.env` 中填入你的配置信息
```shell
cp .env.example .env
```
**注意**：`.env` 文件已添加到 .gitignore 中，请不要推送到代码仓库中以免造成数据泄露

创建 python 虚拟环境
```shell
python3 -m venv venv
```

激活虚拟环境
```shell
# Windows
./venv/Script/Activate

# Linux
source ./venv/bin/activate
```

安装依赖
```shell
pip install -r requirements.txt
```

执行脚本修改步数
```shell
python3 main.py
```


### 执行状态和安全日志

- 所有账号上传成功时退出码为0；任一账号失败或配置错误时退出码为1，GitHub Actions会显示失败。无论账号是否全部成功，已获取的凭据都会尝试保存；保存步骤不会把刷步数失败改为成功。
- Random Cron仍仅在刷步数工作流成功后自动触发，失败时不会修改执行计划。
- 刷步数和Random Cron共用写仓库并发组，使用[GitHub官方并发队列](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)排队串行运行并读取分支最新内容。仅提交指定的凭据/调度文件；如果远端有其他提交则先尝试rebase，文件冲突时停止推送，避免覆盖。
- PushPlus使用[官方支持的HTTPS入口](https://www.pushplus.plus/doc/help/https.html)。网络请求连接超时为5秒、读取超时为20秒；单账号异常后继续处理其他账号。请求不自动跟随重定向。
- 日志不打印token、推送URL或消息正文，常规通知中的账号会脱敏。配置提取仍按手动选择的方式发送原始配置，请保持接收群组私有。
- 步数范围需满足 `0 <= MIN_STEP <= MAX_STEP`；`SLEEP_GAP` 必须为有限非负数，`PUSH_PLUS_MAX` 必须为正整数。

### 本地解密

提取配置工作流输出的Base64密文使用固定IV的CBC；本地凭据缓存使用GCM或旧版随机IV的CBC，请选择对应模式。密钥从环境变量读取，未设置时通过隐藏的交互输入获取，无需写进代码或命令参数。

```shell
# 默认inspect模式：从标准输入输入Base64密文，密钥为INSPECT_AES_KEY
python3 local/decrypt_data.py

# token模式：读取缓存文件，密钥为AES_KEY；兼容旧缓存
python3 local/decrypt_data.py --mode token --file encrypted_tokens.data
```

### 回归检查

项目锁定了直接和间接依赖版本，GitHub Actions也固定到对应版本的提交SHA。更新依赖后应重新验证。

```shell
pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
bash -n cron_convert.sh .github/scripts/persist_changes.sh
shellcheck cron_convert.sh .github/scripts/persist_changes.sh
```

回归测试使用模拟业务接口与临时Git仓库，不访问真实账号或发送通知。`回归测试`工作流会在代码变更和Pull Request时自动执行。


工作流还可用actionlint检查。当前actionlint 1.7.12尚未识别GitHub已文档化的 `concurrency.queue` 字段，检查时仅忽略该条旧语法规则；回归测试另外校验共享并发组、`cancel-in-progress: false` 和 `queue: max`。

```shell
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 -ignore '^unexpected key "queue" for "concurrency" section'
```
