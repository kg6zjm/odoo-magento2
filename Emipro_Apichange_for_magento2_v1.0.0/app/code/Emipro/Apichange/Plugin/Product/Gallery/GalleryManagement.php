<?php
namespace Emipro\Apichange\Plugin\Product\Gallery;

use Magento\Catalog\Api\Data\ProductAttributeMediaGalleryEntryInterface;
use Magento\Store\Model\StoreManagerInterface;

class GalleryManagement
{
	protected $emulation;
	protected $_storeManager;
	public function __construct(StoreManagerInterface $storeManager,
		\Magento\Store\Model\App\Emulation $emulation) 
	{
		$this->_storeManager = $storeManager;
		$this->emulation = $emulation;
	}
    public function beforeCreate(
        \Magento\Catalog\Model\Product\Gallery\GalleryManagement $subject,
        $sku, 
        ProductAttributeMediaGalleryEntryInterface $entry
    ) 
    {
		//$this->_storeManager->setCurrentStore($this->_storeManager->getStore(2));
		//$this->emulation->startEnvironmentEmulation(0, 'adminhtml');
		
		$store_id = $this->_storeManager->getStore(0)->getId();
		/*
        $currentOrder = $subject->getCurrentOrder();
        */
			$objectManager = \Magento\Framework\App\ObjectManager::getInstance();
            $logger=$objectManager->create('Psr\Log\LoggerInterface');
            $logger->debug('message--------dddd-------collection sort my api2');
            $logger->debug($store_id);
        
        /*
        $result = $proceed($collection);
        

        return $result;
        * */
    }
}
