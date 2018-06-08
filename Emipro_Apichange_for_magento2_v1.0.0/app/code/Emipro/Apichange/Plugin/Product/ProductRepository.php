<?php
namespace Emipro\Apichange\Plugin\Product;

class ProductRepository
{

    public function afterGet(\Magento\Catalog\Model\ProductRepository $subject,$result)
    {
        $extensionAttributes = $result->getExtensionAttributes();
        $extensionAttributes->setWebsiteIds($result->getWebsiteIds());
        $result->setExtensionAttributes($extensionAttributes);
        
		return $result;
    }
}
