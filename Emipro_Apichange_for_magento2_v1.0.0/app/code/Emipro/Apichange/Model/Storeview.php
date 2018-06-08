<?php

namespace Emipro\Apichange\Model;

use Emipro\Apichange\Api\StoreviewInterface;
use Magento\Framework\App\ObjectManager;
use Magento\Framework\App\Config;

class Storeview implements StoreviewInterface
{

    private $appConfig;
    protected $storeFactory;

    public function getLists() {
        $objectManager = \Magento\Framework\App\ObjectManager::getInstance();
        $storeManager = $objectManager->get('Magento\Store\Model\StoreManagerInterface');
        $scopeConfig = $objectManager->get('Magento\Framework\App\Config\ScopeConfigInterface');
        $stores = $this->getAppConfig()->get('scopes', "stores", []);
        foreach ($stores as $data) {  
          $language = $scopeConfig->getValue('general/locale/code', \Magento\Store\Model\ScopeInterface::SCOPE_STORE, $data['store_id']);
          $data['language'] = $language;
          $store[] = $data;
        }
        return $store;
    }

    private function getAppConfig()
    {
        if (!$this->appConfig) {
            $this->appConfig = ObjectManager::getInstance()->get(Config::class);
        }
        return $this->appConfig;
    }
}
